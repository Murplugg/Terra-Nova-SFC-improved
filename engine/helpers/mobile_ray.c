/* Stock enemy drone and articulated tank ray contacts. Movement spheres stay intact. */
typedef unsigned int U;typedef unsigned char B;
typedef struct {double x,y,z;} V;
typedef struct {int pivot[3],basis[9];} Joint;
typedef struct {int lo[3],hi[3];U first,last;} Part;
typedef struct {U cl,type,npart;const int (*v)[3];const unsigned short (*t)[3];const Part *p;const Joint *j;const B*header;} Mesh;
#include "mobile_mesh_v71.h"
static V sub(V a,V b){return (V){a.x-b.x,a.y-b.y,a.z-b.z};}
static V cross(V a,V b){return (V){a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static int i32(const void*p){return *(const int*)p;}
static double trig(U a){const short*t=(const short*)0x30f860;U n=(a&65535)>>8,f=a&255;return (t[n]+(((short)(t[n+1]-t[n])*(int)f)>>8))*(1.0/16384.0);}
static const Mesh*mesh(U cl,U type){for(U i=0;i<MESH_COUNT;i++)if(meshes[i].cl==cl&&meshes[i].type==type)return meshes+i;return 0;}
static V vertex(const Mesh*m,U i){return (V){m->v[i][0],m->v[i][1],m->v[i][2]};}
static double intersect(const Mesh*m,const Part*p,V o,V end){
 if((o.x<p->lo[0]&&end.x<p->lo[0])||(o.x>p->hi[0]&&end.x>p->hi[0])||(o.y<p->lo[1]&&end.y<p->lo[1])||(o.y>p->hi[1]&&end.y>p->hi[1])||(o.z<p->lo[2]&&end.z<p->lo[2])||(o.z>p->hi[2]&&end.z>p->hi[2]))return 2;
 V d=sub(end,o);double best=2;
 for(U i=p->first;i<p->last;i++){
  V a=vertex(m,m->t[i][0]),e1=sub(vertex(m,m->t[i][1]),a),e2=sub(vertex(m,m->t[i][2]),a),h=cross(d,e2);
  double det=dot(e1,h);if(det>-0.000001&&det<0.000001)continue;
  V q=sub(o,a);double u=dot(q,h)/det;if(u<0||u>1)continue;
  V k=cross(q,e1);double v=dot(d,k)/det;if(v<0||u+v>1)continue;
  double t=dot(e2,k)/det;if(t>=0&&t<=1&&t<best)best=t;
 }return best;
}
static V body(V q,const B*o,U pitch,int offset){
 U yaw=*(const unsigned short*)(o+27);double s=trig(yaw),co=trig(yaw+16384),sp=trig(pitch),cp=trig(pitch+16384);
 double dx=q.x-i32(o+15),dy=q.y-i32(o+19),dz=q.z-i32(o+23)+offset,forward=dx*co+dy*s;
 return (V){dy*co-dx*s,forward*sp-dz*cp,forward*cp+dz*sp};
}
static V joint(V q,const Joint*j,U angle){
 q=sub(q,(V){j->pivot[0],j->pivot[1],j->pivot[2]});const int*b=j->basis;
 /* Stock bases are exact signed permutations, stored column-major. */
 V r={(q.x*b[0]+q.y*b[1]+q.z*b[2])/65536,(q.x*b[3]+q.y*b[4]+q.z*b[5])/65536,(q.x*b[6]+q.y*b[7]+q.z*b[8])/65536};
 double s=trig(angle),co=trig(angle+16384),n=s*s+co*co;
 return (V){r.x,(co*r.y+s*r.z)/n,(co*r.z-s*r.y)/n};
}
static double contact(const Mesh*m,const B*o,V a,V b,U pitch,int offset,U turret,U barrel){
 a=body(a,o,pitch,offset);b=body(b,o,pitch,offset);double best=intersect(m,m->p,a,b);
 for(U i=1;i<m->npart;i++){
  U angle=i==1?turret:barrel;a=joint(a,m->j+i-1,angle);b=joint(b,m->j+i-1,angle);
  double t=intersect(m,m->p+i,a,b);if(t<best)best=t;
 }return best;
}
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int mobile_mesh_test(U cl,U type,const B*o,const int*ray,U pitch,int offset,U turret,U barrel){
 const Mesh*m=mesh(cl,type);if(!m)return -1;
 double t=contact(m,o,(V){ray[0],ray[1],ray[2]},(V){ray[3],ray[4],ray[5]},pitch,offset,turret,barrel);return t<=1?(int)(t*65536):-1;
}
typedef int(*Prior)(const int*,int,int*,int*,int*,B*);
typedef int(*Pitch)(const B*,const B*);typedef int(*Offset)(U);
#define PRIOR ((Prior)PBA_ENTRY)
#define PITCH ((Pitch)0x1fcf800)
#define OFFSET ((Offset)0x1fcf840)
__attribute__((used,retain,visibility("default"),force_align_arg_pointer)) int mobile_ray(const int*q,int result,int*point,int*out1,int*out2,B*flag){
 result=PRIOR(q,result,point,out1,out2,flag);
 if(q[6]<0x1999)return result;
 V start={q[0]/6.0,q[1]/6.0,q[2]/6.0},dir={q[3]/65536.0,q[4]/65536.0,q[5]/65536.0};
 double norm=dot(dir,dir);if(norm<0.98||norm>1.02)return result;
 V delta={dir.x*q[6]/6.0,dir.y*q[6]/6.0,dir.z*q[6]/6.0},end={start.x+delta.x,start.y+delta.y,start.z+delta.z};
 double best=1.00000001;
 if(result!=-1||*flag){V prior={point[0]/6.0,point[1]/6.0,point[2]/6.0};best=dot(sub(prior,start),delta)/dot(delta,delta);if(best<0)best=0;if(best>1)best=1;}
 int found=-1;
 for(U id=1;id<300;id++){
  const B*o=(const B*)(0x3c3240+id*37);if(!o[0]||!o[34]||o[34]==q[7])continue;
  const Mesh*m=mesh(o[1],o[2]);if(!m)continue;
  U slot=*(const unsigned short*)(o+3);if(!slot||slot>= (o[1]==2?52:40))continue;
  const B*actor=o[1]==2?(const B*)(0x3a19e8+slot*296):(const B*)(0x39e590+slot*335);
  if((*(const unsigned short*)actor&32767)!=id||*(const short*)(actor+6)<=0)continue;
  int idx=((const int*)0x44b9e4)[o[34]];if(idx<0||idx>=96||i32((void*)(0x44e0dd+idx*48))<=i32((void*)0x45d5f0))continue;
  V pos={i32(o+15),i32(o+19),i32(o+23)},diff=sub(pos,start);double t=dot(diff,delta)/dot(delta,delta);if(t<0)t=0;if(t>best)t=best;
  V near={start.x+delta.x*t,start.y+delta.y*t,start.z+delta.z*t},gap=sub(near,pos);
  if(dot(gap,gap)>262144.0*262144.0)continue;
  U pitch=o[1]==2?PITCH(o,m->header):*(const unsigned short*)(o+29);int off=OFFSET(id);
  U a=o[1]==2?*(const unsigned short*)(actor+0x124):0,b=o[1]==2?*(const unsigned short*)(actor+0x126):0;
  double hit=contact(m,o,start,end,pitch,off,a,b);if(hit<best){best=hit;found=o[34];}
 }
 if(found<0)return result;
 point[0]=(int)(q[0]+dir.x*q[6]*best);point[1]=(int)(q[1]+dir.y*q[6]*best);point[2]=(int)(q[2]+dir.z*q[6]*best);*out1=0;*out2=0;*flag=1;return found;
}
