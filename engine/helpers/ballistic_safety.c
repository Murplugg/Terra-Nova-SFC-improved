/* Withhold squad explosives when their curved path predicts a nearby blast
 * that would endanger the shooter or a teammate. Queries preserve engine
 * scratch state and never create a projectile or change an actor pose.
 */
typedef unsigned int U;
typedef unsigned char B;
typedef long long I64;
#define READ(a) (*(volatile int *)(a))
#define TERRAIN ((void (*)(int *,int *,int *,int *))0x1dddc00)
#define SQRT ((int (*)(int))0x1dddd00)
#define EXPORTED __attribute__((used,retain,visibility("default"),force_align_arg_pointer))

typedef struct { int p[3],v[3],gravity,radius,source_index,ignore_index,max_steps,step_ms,terrain_handle; } Launch;
typedef struct { int kind,index,step,point[3],estimated_next[3]; } Result;

/* These original terrain-query temporaries were verified by write tracing.
 * Preserve them so firing admission cannot affect the following world update. */
static const U scratch_address[5]={0x35ed20,0x3c5dc2,0x44659c,0x4465a0,0x4465cc};
static const U scratch_size[5]={16,2,1,4,32};
static int ground_contact(const int *p,int radius,int terrain_handle) {
    B saved[55]; int fields[13]={0}; int x=p[0],y=p[1],z=p[2]; U offset=0;
    for(U i=0;i<5;i++) for(U j=0;j<scratch_size[i];j++)
        saved[offset++]=*(volatile B *)(scratch_address[i]+j);
    fields[12]=terrain_handle; /* Indexes the original explicit terrain-ignore table, not ownership. */
    TERRAIN(&x,&y,&z,fields);
    offset=0;
    for(U i=0;i<5;i++) for(U j=0;j<scratch_size[i];j++)
        *(volatile B *)(scratch_address[i]+j)=saved[offset++];
    return fields[4]!=0 || fields[5]!=0 || (I64)fields[0]>(I64)p[2]-radius;
}

/* Original narrow phase319A23..319B9F, with a fixed96-slot candidate list.
 * Preserve residue order and original lower-distance exclusion. */
EXPORTED int ballistic_contact(const int *p,int radius,int source,int ignore,int *hit,int terrain_handle) {
    *hit=-1;
    if(radius<0 || terrain_handle<0 || terrain_handle>=96) return -1;
    if(ground_contact(p,radius,terrain_handle)) return 1;
    U positions=(U)READ(0x44f2e8);
    for(int order=0;order<96;order++) {
        int index=(order%3)*32+order/3;
        U props=0x44f2ec+160*index;
        if(READ(0x44e0dd+48*index)<=READ(0x45d5f0)) continue;
        if(index==source || index==ignore || READ(props+0x78)==READ(0x45d60c)) continue;
        U center=positions+48*index;
        I64 wide[3]={(I64)p[0]-READ(center),(I64)p[1]-READ(center+16),(I64)p[2]-READ(center+32)-READ(props+0x9c)};
        int delta[3];
        for(int a=0;a<3;a++) {if(wide[a]<-2147483648LL || wide[a]>2147483647LL) return -1;delta[a]=(int)wide[a];}
        I64 sum_wide=(I64)radius+READ(props+0x7c);
        if(sum_wide<0 || sum_wide>2147483647LL) return -1;
        int sum=(int)sum_wide,skip=0;
        for(int axis=0;axis<3;axis++) {
            I64 absolute=delta[axis]<0 ? -(I64)delta[axis] : delta[axis];
            if(absolute>=sum) skip=1;
        }
        if(skip) continue;
        U square=0;
        for(int axis=0;axis<3;axis++) square+=(U)(((I64)delta[axis]*delta[axis])>>16);
        int distance=SQRT((int)square);
        if(distance<sum && distance>0x1999) {*hit=index;return 2;}
    }
    return 0;
}
static int point_at(const Launch *launch,int step,int *point) {
    double time=step*(launch->step_ms/1000.0);
    for(int axis=0;axis<3;axis++) {
        double value=launch->p[axis]+launch->v[axis]*time;
        if(axis==2) value-=0.5*launch->gravity*time*time;
        if(!(value>-2147483647.0 && value<2147483646.0)) return 0;
        point[axis]=(int)(value+(value<0?-0.5:0.5));
    }
    return 1;
}
/* A budget expiry means unknown, never a proof of a safe shot. The next position
 * corresponds to the blast position for body contact; terrain contact uses
 * the detection position. Both follow the engine update/contact order. */
EXPORTED int ballistic_forecast(const Launch *launch,Result *result) {
    result->kind=-1;result->index=-1;result->step=0;
    if(launch->max_steps<1 || launch->max_steps>1024 || launch->step_ms<1 || launch->step_ms>100 || launch->radius<0) return -1;
    for(int step=0;step<=launch->max_steps;step++) {
        if(!point_at(launch,step,result->point)) return -1;
        /* Actual physics uses this scale and deletes beyond these buckets. */
        int scale=READ(0x4534f4);
        for(int axis=0;axis<2;axis++) {
            I64 bucket=((I64)result->point[axis]*scale)>>32;
            if(bucket<=1 || bucket>=99) return -1;
        }
        int kind=ballistic_contact(result->point,launch->radius,launch->source_index,launch->ignore_index,&result->index,launch->terrain_handle);
        if(kind) {
            result->kind=kind;result->step=step;
            if(!point_at(launch,step+1,result->estimated_next)) return -1;
            return kind;
        }
    }
    return -1;
}

#define SHAPE_DISTANCE ((int (*)(int,const int *))0x1ddde00)

static int active_faction(int object) {
    U record=0x3c3240+37*object;
    if(!*(volatile B *)record) return -1;
    int ai=*(volatile B *)(record+33);
    if(ai<1 || ai>=60) return -1;
    U state=0x3832f0+334*ai;
    if(!(*(volatile B *)state || *(volatile B *)(state+10))) return -1;
    return *(volatile B *)(state+5);
}

/* This admission rule is scoped to squad Missile Launcher/M-B Cannon shots.
 * Unknown trajectories retain existing admission; player and enemy firing are
 * unchanged. Forecasts use current actor positions, so they are conservative
 * around moving units. The existing controller can reposition after refusal.
 */
EXPORTED int ballistic_unsafe(const int *position_velocity,int owner,int weapon,const int *parameters) {
    if(owner<1 || owner>=300 || (weapon!=10 && weapon!=13)) return 0;
    int player=*(volatile unsigned short *)0x441350;
    if(owner==player || player<1 || player>=300) return 0;
    if(*(volatile B *)(0x3c3241+37*owner)!=1) return 0;
    int faction=active_faction(owner);
    if(faction<0 || faction!=active_faction(player)) return 0;
    int handle=*(volatile B *)(0x3c3262+37*owner);
    if(handle<1 || handle>=96 || READ(0x4464b8+4*handle)!=0) return 0;
    int source=READ(0x44b9e4+4*handle);
    if(source<0 || source>=96 || READ(0x44bb64+4*source)!=handle) return 0;
    Launch launch;
    for(int axis=0;axis<3;axis++) {
        launch.p[axis]=position_velocity[axis];
        launch.v[axis]=position_velocity[axis+3];
    }
    launch.gravity=parameters[2];launch.radius=parameters[1];
    launch.source_index=source;launch.ignore_index=-1;
    launch.step_ms=17;launch.max_steps=176;launch.terrain_handle=handle;
    Result result;
    int kind=ballistic_forecast(&launch,&result);
    if(kind!=1 && kind!=2) return 0;
    int *point=kind==2 ? result.estimated_next : result.point;
    int cells[3];
    for(int axis=0;axis<3;axis++) cells[axis]=point[axis]/6;
    int blast=*(volatile B *)(0x395110+36*weapon+7);
    int radius=READ(0x396404+9*blast+2);
    if(radius<=0) return 0;
    for(int object=1;object<300;object++) {
        int type=*(volatile B *)(0x3c3241+37*object);
        if((type!=1 && type!=2) || active_faction(object)!=faction) continue;
        int distance=SHAPE_DISTANCE(object,cells);
        if(distance>=0 && distance<radius) return 1;
    }
    return 0;
}
