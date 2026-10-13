/* Supplemental articulated leg ray contacts. Original body/movement contacts remain. */
typedef unsigned int U; typedef unsigned char B;
typedef struct { double x,y,z; } V;
static V sub(V a,V b){return (V){a.x-b.x,a.y-b.y,a.z-b.z};}
static V add(V a,V b){return (V){a.x+b.x,a.y+b.y,a.z+b.z};}
static V mul(V a,double t){return (V){a.x*t,a.y*t,a.z*t};}
static double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static int i32(const void*p){return *(const int*)p;}
static V vec(const void*p){const int*q=p;return (V){q[0],q[1],q[2]};}
static double sphere(V o,V d,V a,double r){
 V q=sub(o,a);double aa=dot(d,d),b=dot(q,d),cc=dot(q,q)-r*r;
 if(cc<=0)return 0;
 double h=b*b-aa*cc;if(h<0||aa<1)return 2;
 double t=(-b-__builtin_sqrt(h))/aa;return t>=0&&t<=1?t:2;
}
static double capsule(V o,V d,V a,V b,double r){
 V ba=sub(b,a),oa=sub(o,a);double bb=dot(ba,ba),dd=dot(d,d),bd=dot(ba,d),bo=dot(ba,oa),od=dot(oa,d),oo=dot(oa,oa);
 double best=sphere(o,d,a,r),t=sphere(o,d,b,r);if(t<best)best=t;
 if(bb<1)return best;
 double f=bo/bb;if(f>=0&&f<=1&&oo-bo*bo/bb<=r*r)return 0;
 double A=bb*dd-bd*bd,Bb=bb*od-bo*bd,Cc=bb*oo-bo*bo-r*r*bb;
 double h=Bb*Bb-A*Cc;
 if(A>0.000001&&h>=0){t=(-Bb-__builtin_sqrt(h))/A;double y=bo+t*bd;if(t>=0&&t<=1&&y>=0&&y<=bb&&t<best)best=t;}
 return best;
}
typedef void (*Pose)(B*,int);
#define POSE ((Pose)0x1eff000)
typedef int (*Prior)(const int*,int,int*,int*,int*,B*);
#define PRIOR ((Prior)VEHICLE_ENTRY)
/* The original pose evaluator uses this bounded global scratch range. */
static int joints(const B*obj,const B*suit,V*j){
 B pose[0x350],scratch[0x50],mathscratch[36];const B*src=suit+0xde;
 if(i32(src)>10||src[4]==3)return 0;
 int leg=i32(src+0x2fe);if(leg<2000||leg>65536)return 0;
 V position=vec(obj+15);
 /* Reject malformed/spawn poses; the separate renderer repair still owns them. */
 for(U i=2;i<8;i++){
  if(i==4||i==5)continue; /* Knees may be stale until this private evaluation. */
  V p=vec(src+0xd1+i*12),delta=sub(p,position);
  if(dot(delta,delta)>(double)(leg*4)*(leg*4))return 0;
 }
 for(U i=0;i<sizeof(pose);i++)pose[i]=src[i];
 for(U i=0;i<sizeof(scratch);i++)scratch[i]=((volatile B*)0x3924b0)[i];
 for(U i=0;i<sizeof(mathscratch);i++)mathscratch[i]=((volatile B*)0x360568)[i];
 B tile=*(volatile B*)0x44659c;
 /* Refresh a private copy: original animation/gameplay state is never advanced. */
 *(int*)(pose+5)=0;POSE(pose,16);
 for(U i=0;i<sizeof(scratch);i++)((volatile B*)0x3924b0)[i]=scratch[i];
 for(U i=0;i<sizeof(mathscratch);i++)((volatile B*)0x360568)[i]=mathscratch[i];
 *(volatile B*)0x44659c=tile;
 for(U i=0;i<8;i++){
  j[i]=vec(pose+0xd1+i*12);V delta=sub(j[i],position);
  if(dot(delta,delta)>(double)(leg*4)*(leg*4))return 0;
 }
 return leg;
}
/* Test entry accepts independent ray endpoints and one capsule. */
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int pba_capsule_test(const int*q){
 V a=vec(q),b=vec(q+3);double t=capsule(a,sub(b,a),vec(q+6),vec(q+9),q[12]);return t<=1?(int)(t*65536):-1;
}
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int pba_joints_test(const B*obj,const B*suit,int*out){
 V j[8];int leg=joints(obj,suit,j);if(!leg)return 0;
 for(U i=0;i<8;i++){out[i*3]=(int)j[i].x;out[i*3+1]=(int)j[i].y;out[i*3+2]=(int)j[i].z;}return leg;
}
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int pba_ray(const int*q,int result,int*point,int*out1,int*out2,B*flag){
 result=PRIOR(q,result,point,out1,out2,flag);
 if(q[6]<0x1999)return result;
 V start=mul(vec(q),1.0/6.0),direction=mul(vec(q+3),1.0/65536.0);double norm=dot(direction,direction);
 if(norm<0.98||norm>1.02)return result;
 V delta=mul(direction,q[6]/6.0);double dd=dot(delta,delta),best=1.00000001;
 if(result!=-1||*flag){best=dot(sub(mul(vec(point),1.0/6.0),start),delta)/dd;if(best<0)best=0;if(best>1)best=1;}
 int found=-1;
 for(U id=1;id<300;id++){
  const B*obj=(const B*)(0x3c3240+id*37);
  if(!obj[0]||obj[1]!=1||!obj[34]||obj[34]==q[7])continue;
  U slot=*(const unsigned short*)(obj+3);if(!slot||slot>=60)continue;
  const B*suit=(const B*)(0x3a5608+slot*0x582);
  if((*(const unsigned short*)suit&32767)!=id)continue;
  U health=*(const U*)(suit+0x9c);if(health<0x11000||health>0x1ffff00||*(const short*)(health+3)<=0)continue;
  int idx=((const int*)0x44b9e4)[obj[34]];if(idx<0||idx>=96||i32((void*)(0x44e0dd+idx*48))<=i32((void*)0x45d5f0))continue;
  V pos=vec(obj+15);double t=dot(sub(pos,start),delta)/dd;if(t<0)t=0;if(t>best)t=best;
  V gap=sub(add(start,mul(delta,t)),pos);if(dot(gap,gap)>65536.0*65536.0)continue;
  V j[8];int leg=joints(obj,suit,j);if(!leg)continue;
  double radius=leg*0.10;
  /* Separate foot, shin and thigh volumes leave the inter-leg gap open. */
  for(U side=0;side<2;side++)for(U part=0;part<3;part++){
   U a=side+part*2,b=a+2;double hit=capsule(start,delta,j[a],j[b],radius);
   if(hit<best){best=hit;found=obj[34];}
  }
 }
 if(found<0)return result;
 point[0]=(int)(q[0]+direction.x*q[6]*best);point[1]=(int)(q[1]+direction.y*q[6]*best);point[2]=(int)(q[2]+direction.z*q[6]*best);
 *out1=0;*out2=0;*flag=1;return found;
}
