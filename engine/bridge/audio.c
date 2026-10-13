/* Native PCM hardware boundary. Original Miles sample layout and decoders remain
 * in the game. All sample changes and callbacks run on the game thread. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stddef.h>
#define API __declspec(dllexport)
#define NS 32
#define RATE 48000
#define FRAMES 1024
#define NBUF 4
typedef struct { uint32_t w[0x894/4]; } Sample;
#define V(s,o) ((s)->w[(o)/4])
typedef struct { uint32_t fraction,stream,started; } Extra;
static Sample samples[NS];
static Extra extra[NS];
static uint32_t driver[0x400/4];
static HWAVEOUT wave;
static WAVEHDR headers[NBUF];
static int16_t output[NBUF][FRAMES*2];
static uint32_t head,prepared,opened,busy,ever_queued;
static uint32_t modal_depth;
/* Read-only probe obtains this pointer through TN_GetStats. */
static uint32_t stats[32];
static uint32_t gain(uint32_t x){return (int32_t)x<0?0:(x>127?127:x);}
extern uint32_t tn_original(uint32_t fn, uint32_t a, uint32_t b, uint32_t c);
static int index_of(Sample *s) {
 uintptr_t p=(uintptr_t)s,b=(uintptr_t)samples;
 if(p<b || p>=b+sizeof(samples) || (p-b)%sizeof(Sample))return -1;
 return (int)((p-b)/sizeof(Sample));
}
static void callback(Sample *s,uint32_t off) {
 uint32_t fn=V(s,off);if(fn){stats[6]++;tn_original(fn,(uint32_t)s,0,0);}
}
static void finish(Sample *s) {
 V(s,4)=2;stats[5]++;callback(s,0x850);
}
static int ready_frame(Sample *s,Extra *e) {
 for(int tries=0;tries<8 && V(s,4)==4;tries++) {
  uint32_t b=V(s,0x28)&1,step=(1u<<(V(s,0x34)&1))*(1u<<((V(s,0x34)>>1)&1));
  if(V(s,8+b*4) && V(s,0x18+b*4)+step<=V(s,0x10+b*4)) {
   if(!e->started){e->started=1;callback(s,0x848);if(V(s,4)!=4)return 0;}
   return 1;
  }
  if(!e->stream) {
   if(!V(s,0x10+b*4)){finish(s);return 0;}
   callback(s,0x84c);if(V(s,4)!=4)return 0;
   if(V(s,0x30)!=1) {
    if(V(s,0x30)>1)V(s,0x30)--;
    V(s,0x18+b*4)=0;e->started=0;continue;
   }
   finish(s);e->started=0;continue; /* VOC EOS may start the next block. */
  }
  uint32_t other=b^1;
  if(V(s,0x20+other*4)){callback(s,0x84c);finish(s);return 0;}
  if(!V(s,8+other*4) || V(s,0x18+other*4)>=V(s,0x10+other*4))return 0;
  callback(s,0x84c);if(V(s,4)!=4)return 0;
  V(s,0x28)=other;e->started=0;stats[7]++;
 }
 return 0;
}
static int pcm(const uint8_t *p,uint32_t format,uint32_t flags) {
 if(format&1){int v=p[0]|(p[1]<<8);return flags&1?(int16_t)v:v-32768;}
 return flags&1?(int)(int8_t)*p*256:((int)*p-128)*256;
}
static void mix(int16_t *out,uint32_t frames) {
 for(uint32_t f=0;f<frames;f++) {
  int64_t left=0,right=0;
  for(int i=0;i<NS;i++) {
   Sample *s=&samples[i];Extra *e=&extra[i];
   if(V(s,4)!=4 || !ready_frame(s,e))continue;
   uint32_t b=V(s,0x28)&1,fmt=V(s,0x34),width=1u<<(fmt&1),stereo=(fmt>>1)&1;
   const uint8_t *p=(void *)(uintptr_t)(V(s,8+b*4)+V(s,0x18+b*4));
   int l=pcm(p,fmt,V(s,0x38)),r=stereo?pcm(p+width,fmt,V(s,0x38)):l;
   uint32_t vol=gain(V(s,0x40)),pan=gain(V(s,0x44));
   uint32_t master=gain(driver[0x68/4]);
   uint32_t lg=pan<=64?64:(127-pan)*64/63,rg=pan>=64?64:pan;
   left+=(int64_t)l*vol*master*lg/(127*127*64);
   right+=(int64_t)r*vol*master*rg/(127*127*64);
   uint32_t rate=V(s,0x3c);if(rate>192000)rate=192000;
   e->fraction+=rate;
   while(e->fraction>=RATE && V(s,4)==4) {
    e->fraction-=RATE;b=V(s,0x28)&1;
    V(s,0x18+b*4)+=(1u<<(V(s,0x34)&1))*(1u<<((V(s,0x34)>>1)&1));
    if(!ready_frame(s,e)){e->fraction=0;break;}
   }
  }
  left/=10;right/=10; /* Conservative local gain; never touches system volume. */
  if(left>32767)left=32767;if(left< -32768)left=-32768;
  if(right>32767)right=32767;if(right< -32768)right=-32768;
  out[f*2]=(int16_t)left;out[f*2+1]=(int16_t)right;
  if(left||right)stats[4]++;
 }
 stats[3]+=frames;
}
API uint32_t *TN_GetStats(void){return stats;}
API void TN_Pump(void) {
 if(!opened || busy || modal_depth)return;busy=1;stats[1]++;
 uint32_t queued=0;for(int i=0;i<NBUF;i++)if(headers[i].dwFlags&WHDR_INQUEUE)queued++;
 if(!queued && ever_queued)stats[8]++;
 for(int count=0;count<NBUF;count++) {
  WAVEHDR *h=&headers[head];if(h->dwFlags&WHDR_INQUEUE)break;
  mix(output[head],FRAMES);
  MMRESULT rc=waveOutWrite(wave,h,sizeof(*h));if(rc){stats[9]=rc;break;}
  stats[2]++;ever_queued=1;head=(head+1)%NBUF;
 }
 busy=0;
}
API void TN_UninstallDIG(void *unused) {
 (void)unused;if(wave){waveOutReset(wave);for(uint32_t i=0;i<prepared;i++)waveOutUnprepareHeader(wave,&headers[i],sizeof(WAVEHDR));waveOutClose(wave);}
 wave=0;opened=prepared=0;stats[0]=0;
}

/* Host timing is shared by the movie and original system clocks. */
#define MEM32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define MEM64(a) (*(volatile uint64_t *)(uintptr_t)(a))
static uint64_t last_sample,modal_start,next_frame;
static HANDLE frame_timer;
static HWAVEOUT legacy_wave;
static int in_frame_wait;
static uint64_t counter(void){LARGE_INTEGER q;QueryPerformanceCounter(&q);return (uint64_t)q.QuadPart;}
static uint64_t frequency(void){return MEM64(0x1d0f120);}
static void pump_window(void){((void (*)(void))(uintptr_t)0x1d19000)();}
static int mission_active(void){return MEM32(0x1d0b000)==0x103 && *(volatile uint8_t *)0x35f3f4==0;}
API void TN_BindLegacyAudio(uint32_t handle){legacy_wave=(HWAVEOUT)(uintptr_t)handle;}
API uint32_t TN_TimeMS(void) {
 uint64_t now=counter(),hz=frequency();if(!hz)return 0;
 if(modal_depth)return (uint32_t)(((modal_start-MEM64(0x1d0f110))*1000)/hz);
 if(last_sample && now-last_sample>hz && !modal_depth){
  MEM64(0x1d0f110)+=now-last_sample;stats[19]++;next_frame=0;
 }
 last_sample=now;
 return (uint32_t)(((now-MEM64(0x1d0f110))*1000)/hz);
}
API void TN_Suspend(void) {
 if(modal_depth++==0){modal_start=counter();HWAVEOUT h=wave?wave:legacy_wave;
  if(h){MMRESULT rc=waveOutPause(h);if(rc)stats[9]=rc;}
  stats[17]++;
 }
}
API void TN_Resume(void) {
 if(!modal_depth)return;
 if(--modal_depth==0){
  uint64_t now=counter(),held=now-modal_start,hz=frequency();
  MEM64(0x1d0f110)+=held;last_sample=now;next_frame=0;
  if(hz)stats[18]+=(uint32_t)(held*1000/hz);
  HWAVEOUT h=wave?wave:legacy_wave;if(h){MMRESULT rc=waveOutRestart(h);if(rc)stats[9]=rc;}
 }
}
API void TN_FrameBegin(void) {
 if(in_frame_wait)return;
 if(!mission_active()){next_frame=0;return;}
 in_frame_wait=1;
 uint64_t hz=frequency(),now=counter(),period=hz/60;
 if(!period){in_frame_wait=0;return;}
 if(!next_frame || now>next_frame+hz/4)next_frame=now;
 while(now<next_frame){
  pump_window();now=counter();
  if(!mission_active() || !next_frame)break;
  if(now>=next_frame)break;
  uint64_t remaining=(next_frame-now)*10000000/hz;
  if(remaining>20000)remaining=20000;
  if(!frame_timer)frame_timer=CreateWaitableTimerExW(0,0,2,TIMER_ALL_ACCESS);
  if(frame_timer){LARGE_INTEGER due;due.QuadPart=-(LONGLONG)(remaining?remaining:1);
   if(SetWaitableTimer(frame_timer,&due,0,0,0,FALSE))WaitForSingleObject(frame_timer,20);
   else Sleep(0);
  }else Sleep(1);
  stats[22]++;now=counter();
 }
 if(mission_active()){next_frame=(next_frame && now-next_frame<period)?next_frame+period:now+period;stats[20]++;}
 else next_frame=0;
 in_frame_wait=0;
}
API void TN_FrameEnd(void) {
 if(mission_active()){MEM32(0x1d1d080)=1;pump_window();stats[21]++;}
}
API void *TN_InstallDIG(const char *name,const void *io) {
 (void)name;if(opened)return driver;
 memset(samples,0,sizeof(samples));memset(extra,0,sizeof(extra));memset(driver,0,sizeof(driver));memset(stats,0,sizeof(stats));
 for(int i=0;i<NS;i++){V(&samples[i],0)=(uint32_t)driver;V(&samples[i],4)=1;}
 driver[0x5c/4]=(uint32_t)samples;driver[0x60/4]=NS;driver[0x68/4]=127;driver[0x54/4]=1;
 driver[0x18/4]=3;driver[0x3c/4]=2;driver[0x14/4]=RATE;
 if(io)memcpy((void *)0x45f2fc,io,8);
 WAVEFORMATEX format={WAVE_FORMAT_PCM,2,RATE,RATE*4,4,16,0};
 MMRESULT rc=waveOutOpen(&wave,WAVE_MAPPER,&format,0,0,CALLBACK_NULL);stats[9]=rc;if(rc)return 0;
 memset(headers,0,sizeof(headers));head=prepared=ever_queued=0;
 for(int i=0;i<NBUF;i++) {
  headers[i].lpData=(LPSTR)output[i];headers[i].dwBufferLength=sizeof(output[i]);
  rc=waveOutPrepareHeader(wave,&headers[i],sizeof(WAVEHDR));if(rc){stats[9]=rc;TN_UninstallDIG(0);return 0;}prepared++;
 }
 opened=1;stats[0]=1;stats[10]=(uint32_t)samples;stats[11]=NS;stats[12]=(uint32_t)driver;
 TN_Pump();return driver;
}
API void *TN_InstallMDI(const char *name,const void *io){(void)name;(void)io;stats[13]++;return 0;}
API void TN_InitSample(Sample *s) {
 int i=index_of(s);if(i<0)return;memset(&extra[i],0,sizeof(Extra));
 tn_original(0x320124,(uint32_t)s,0,0);stats[14]++;
}
API void TN_StartSample(Sample *s) {
 int i=index_of(s);if(i<0)return;extra[i].fraction=extra[i].started=0;
 tn_original(0x32030c,(uint32_t)s,0,0);stats[15]++;
}
API void TN_LoadBuffer(Sample *s,uint32_t b,void *data,uint32_t length) {
 int i=index_of(s);if(i<0 || b>1)return;
 extra[i].stream=1;V(s,0x18+b*4)=0;V(s,0x20+b*4)=length==0;
 V(s,0x10+b*4)=length;V(s,8+b*4)=(uint32_t)data;if(length)V(s,4)=4;stats[16]++;
}
API uint32_t TN_MinimumBuffer(void *dig,uint32_t rate,uint32_t format) {
 (void)dig;uint32_t bytes=(rate/10)*(1u<<(format&1))*(1u<<((format>>1)&1));
 if(bytes<256)bytes=256;if(bytes>262144)bytes=262144;return (bytes+255)&~255u;
}
/* Deterministic mixer tests have no device output and need no game assets. */
static void test_sample(Sample *s,void *data,uint32_t bytes,uint32_t fmt,uint32_t flags) {
 memset(samples,0,sizeof(samples));memset(extra,0,sizeof(extra));memset(driver,0,sizeof(driver));driver[0x68/4]=127;
 V(s,4)=4;V(s,8)=(uint32_t)data;V(s,0x10)=bytes;V(s,0x24)=1;V(s,0x30)=1;
 V(s,0x34)=fmt;V(s,0x38)=flags;V(s,0x3c)=RATE;V(s,0x40)=127;V(s,0x44)=64;
}
static uint32_t test_eos_count,test_eob_count;
static void test_eos(Sample *s){(void)s;test_eos_count++;}
static void test_eob(Sample *s){(void)s;test_eob_count++;}
API uint32_t TN_SelfTest(void) {
 uint32_t fail=0;int16_t out[32];Sample *s=samples;uint8_t u8[]={128,255,0,128};
 test_sample(s,u8,4,0,0);mix(out,4);if(out[0]||out[2]!=3251||out[4]!=-3276||V(s,4)!=2)fail|=1;
 int16_t stereo[]={10000,-10000,20000,-20000};test_sample(s,stereo,8,3,1);mix(out,2);if(out[0]!=1000||out[1]!=-1000||out[2]!=2000||V(s,4)!=2)fail|=2;
 test_sample(s,u8+1,1,0,0);V(s,0x30)=3;mix(out,4);if(out[0]!=3251||out[4]!=3251||out[6]||V(s,4)!=2)fail|=4;
 test_sample(s,u8+1,1,0,0);V(s,0x30)=0;mix(out,8);if(out[14]!=3251||V(s,4)!=4)fail|=8;
 test_sample(s,u8,4,0,0);V(s,0x3c)=RATE/2;mix(out,8);if(out[4]!=3251||out[8]!=-3276||V(s,4)!=2)fail|=16;
 test_sample(s,u8+1,1,0,0);V(s,0x24)=0;extra[0].stream=1;V(s,0xc)=(uint32_t)(u8+2);V(s,0x14)=1;
 mix(out,2);if(out[0]!=3251||out[2]!=-3276||V(s,0x28)!=1||V(s,4)!=4)fail|=32;
 V(s,0x20)=1;mix(out,1);if(V(s,4)!=2||out[0])fail|=64;
 test_sample(s,u8+1,1,0,0);V(s,0x44)=0;mix(out,1);if(out[0]!=3251||out[1])fail|=128;
 test_sample(s,u8+1,1,0,0);V(s,0x40)=0;mix(out,1);if(out[0]||out[1])fail|=256;
 test_sample(s,u8+1,1,0,0);V(s,4)=8;mix(out,1);if(out[0]||V(s,0x18))fail|=512;
 test_sample(s,u8+1,1,0,0);V(s,0x850)=(uint32_t)test_eos;V(s,0x84c)=(uint32_t)test_eob;
 test_eos_count=test_eob_count=0;mix(out,4);if(test_eos_count!=1||test_eob_count!=1)fail|=1024;
 test_sample(s,u8+1,1,0,0);V(s,0x40)=(uint32_t)-1;mix(out,1);if(out[0]||out[1])fail|=2048;
 int8_t signed8[]={127,-128};test_sample(s,signed8,2,0,1);mix(out,2);if(out[0]!=3251||out[2]!=-3276)fail|=4096;
 uint16_t unsigned16[]={32768,65535,0};test_sample(s,unsigned16,6,1,0);mix(out,3);if(out[0]||out[2]!=3276||out[4]!=-3276)fail|=8192;
 test_sample(s,u8,4,0,0);V(s,0x3c)=RATE*2;mix(out,2);if(out[0]||out[2]!=-3276||V(s,4)!=2)fail|=16384;
 test_sample(s,u8+1,1,0,0);V(s,0x24)=0;extra[0].stream=1;mix(out,2);if(out[0]!=3251||out[2]||V(s,4)!=4)fail|=32768;
 TN_LoadBuffer(s,1,u8+2,1);mix(out,1);if(out[0]!=-3276||V(s,0x28)!=1)fail|=65536;
 return fail;
}
#ifdef TN_TEST
int main(void){uint32_t f=TN_SelfTest();printf("{\"mixer_checks\":17,\"failure_mask\":%u}\n",f);return f?1:0;}
#endif
