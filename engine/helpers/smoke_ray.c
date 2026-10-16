/* Smoke follows its living particles. A cloud must not leave an invisible
   column behind when it rises, or gain blocking chances from more frames. */
typedef unsigned int U;
typedef unsigned char B;
typedef struct { double x, y, z; } Vec;
typedef int (*Prior)(const int *, int, int *, int *, int *, B *);
typedef void (*Transform)(int, int *);
#define TRANSFORM ((Transform)0x1d3a200)
#define CONTEXT (*(volatile U *)0x1d3b004)
#define CLOUD_SERIAL ((const U *)0x1d3b800)

static int word(const void *p) { return *(const int *)p; }
static Vec sub(Vec a, Vec b) { return (Vec){a.x-b.x, a.y-b.y, a.z-b.z}; }
static double dot(Vec a, Vec b) { return a.x*b.x + a.y*b.y + a.z*b.z; }
static U mix(U n) {
    n ^= n >> 16; n *= 0x7feb352d;
    n ^= n >> 15; n *= 0x846ca68b;
    return n ^ (n >> 16);
}

/* Keep the original count/4 percentage, but draw it once per shot/cloud
   identity. Particle expiry can lower the threshold; extra query calls cannot
   manufacture new random chances. No gameplay random stream is consumed. */
__attribute__((used,retain,visibility("default")))
int smoke_roll(U shot, U cloud, U count) {
    return mix(shot ^ mix(cloud)) % 100 < (count >> 2);
}

static int group_for(int handle) {
    int capacity=word((void *)0x421a08);
    if (handle < 0 || handle >= capacity || handle >= 256) return -1;
    int group=((const int *)word((void *)0x421a18))[handle];
    return group >= 0 && group < word((void *)0x421a0c) && group < 256 ? group : -1;
}

/* The helper uses the renderer's own group matrix, including rotation and
   scale. Puff radii match the original 320-pixel view's projected footprint:
   modes 0/1 use 50/depth pixels, and mode 8 uses 20/depth pixels. */
static Vec centre(const int *m, const short *p) {
    double v[3];
    for (int k=0; k<3; ++k)
        v[k]=m[9+k]+((double)m[k*3]*p[0]+(double)m[k*3+1]*p[1]+(double)m[k*3+2]*p[2])/256;
    return (Vec){v[0],v[1],v[2]};
}

static double sphere(Vec start, Vec delta, Vec c, double radius) {
    Vec d=sub(start,c);
    double a=dot(delta,delta), b=dot(d,delta), v=dot(d,d)-radius*radius;
    if (v <= 0) return 0;
    if (a <= 0 || b >= 0) return 2;
    double disc=b*b-a*v;
    if (disc < 0) return 2;
    double t=(-b-__builtin_sqrt(disc))/a;
    return t >= 0 && t <= 1 ? t : 2;
}

__attribute__((used,retain,visibility("default"),force_align_arg_pointer))
int smoke_contact(int handle, const int *ray, U shot, U identity) {
    int group=group_for(handle);
    if (group < 0) return -1;
    const B *g=(const B *)word((void *)0x421a1c)+group*16;
    int mode=g[14];
    if (mode != 0 && mode != 1 && mode != 8) return -1;
    const int *interval=(const int *)word((void *)0x421a14)+group;
    int first=interval[0], last=interval[1];
    if (first < 0 || last <= first || last > word((void *)0x421a24)) return -1;
    if (!smoke_roll(shot,identity,(U)(last-first))) return -1;
    int matrix[12];
    TRANSFORM(group,matrix);
    Vec start={ray[0]/6.0,ray[1]/6.0,ray[2]/6.0};
    Vec delta={(double)ray[3]*ray[6]/393216.0,(double)ray[4]*ray[6]/393216.0,(double)ray[5]*ray[6]/393216.0};
    const B *particles=(const B *)word((void *)0x421a20);
    double best=2, radius=mode==8 ? 8192 : 20480;
    for (int i=first;i<last;++i) {
        double hit=sphere(start,delta,centre(matrix,(const short *)(particles+i*12)),radius);
        if (hit < best) best=hit;
    }
    return best <= 1 ? (int)(best*65536) : -1;
}

__attribute__((used,retain,visibility("default"),force_align_arg_pointer))
int smoke_ray(const int *ray,int result,int *point,int *out1,int *out2,B *flag) {
    U shot=CONTEXT;
    CONTEXT=0;
    result=((Prior)MOBILE_ENTRY)(ray,result,point,out1,out2,flag);
    if (ray[6] <= 0) return result;
    Vec direction={ray[3]/65536.0,ray[4]/65536.0,ray[5]/65536.0};
    double norm=dot(direction,direction);
    if (norm < .98 || norm > 1.02) return result;
    double best=65537;
    if (result != -1 || *flag) {
        Vec gap={point[0]-(double)ray[0],point[1]-(double)ray[1],point[2]-(double)ray[2]};
        best=dot(gap,direction)/ray[6]*65536;
        if (best < 0) best=0;
        if (best > 65536) best=65536;
    }
    /* Sight/picking queries have no projectile identity. A short game-time
       bucket keeps their obstruction stable within an AI update, without
       tying it to render frames or perturbing the game's shared RNG. */
    if (!shot) shot=mix((U)word((void *)0x446ae8)/250 ^ (U)ray[0] ^ (U)ray[1]);
    int found=0;
    for (int id=1;id<300;++id) {
        const B *o=(const B *)(0x3c3240+id*37);
        if (!o[0] || o[1]!=6 || o[2]!=29) continue;
        U slot=*(const unsigned short *)(o+3);
        if (!slot || slot>=256) continue;
        const B *effect=(const B *)(0x1e20000+slot*44);
        if (!(effect[42]&8)) continue;
        int handle=word(effect+10);
        if (handle < 0 || handle >= 256) continue;
        U identity=mix(CLOUD_SERIAL[handle] ^ (U)id ^ (U)word(o+15) ^ (U)word(o+19));
        int hit=smoke_contact(handle,ray,shot,identity);
        if (hit >= 0 && hit < best) { best=hit; found=id; }
    }
    if (!found) return result;
    point[0]=(int)(ray[0]+direction.x*ray[6]*best/65536);
    point[1]=(int)(ray[1]+direction.y*ray[6]*best/65536);
    point[2]=(int)(ray[2]+direction.z*ray[6]*best/65536);
    *out1=found; *out2=0; *flag=1;
    return -1;
}
