/* Tests the real display bridge with recorded GDI calls. No game data needed.
 * Compile as a Windows executable with Zig; see docs/testing.md. The mocks let
 * resize painting be checked without opening a window or depending on a GPU. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static uint32_t state[0x14000/4];
#define D(a) state[((a)-0x1d0b000)/4]
static RECT client;
static int paints,ends,stretches,fills,forwards;
static int dst[4],src[2];
static HDC WINAPI begin(HWND h,LPPAINTSTRUCT ps){(void)h;(void)ps;paints++;return (HDC)1;}
static BOOL WINAPI end(HWND h,const PAINTSTRUCT *ps){(void)h;(void)ps;ends++;return TRUE;}
static BOOL WINAPI rect(HWND h,LPRECT r){(void)h;*r=client;return TRUE;}
static int WINAPI fill(HDC h,const RECT *r,HBRUSH b){(void)h;(void)r;(void)b;fills++;return 1;}
static int WINAPI stretch_mode(HDC h,int mode){(void)h;return mode;}
static int WINAPI stretch(HDC dc,int x,int y,int w,int h,int sx,int sy,int sw,int sh,
 const void *bits,const BITMAPINFO *info,UINT use,DWORD rop){
 (void)dc;(void)sx;(void)sy;(void)bits;(void)info;(void)use;(void)rop;
 stretches++;dst[0]=x;dst[1]=y;dst[2]=w;dst[3]=h;src[0]=sw;src[1]=sh;return sh;
}
static LRESULT CALLBACK forwarded(HWND h,UINT m,WPARAM w,LPARAM l){
 (void)h;(void)m;(void)w;(void)l;forwards++;return 85;
}
#define TN_GAME_WINDOW_PROC forwarded
#define BeginPaint begin
#define EndPaint end
#define GetClientRect rect
#define FillRect fill
#define SetStretchBltMode stretch_mode
#define StretchDIBits stretch
#include "../engine/bridge/display.c"
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static void layout(int cw,int ch,int w,int h,int dw,int dh){
 D(0x1d1d248)=cw;D(0x1d1d24c)=ch;D(0x1d1d010)=w;D(0x1d1d014)=h;
 TN_Layout();CHECK(D(0x1d1d098)==(uint32_t)dw&&D(0x1d1d09c)==(uint32_t)dh);
 CHECK(D(0x1d1d090)==(uint32_t)(cw-dw)/2&&D(0x1d1d094)==(uint32_t)(ch-dh)/2);
}
int main(void){
 layout(800,600,1280,960,800,600);layout(1000,600,1280,960,800,600);
 layout(800,800,1280,960,800,600);layout(1920,1080,1280,960,1280,960);
 layout(2560,1920,1280,960,2560,1920);layout(0,0,1280,960,0,0);
 for(int cw=1;cw<=3000;cw+=37)for(int ch=1;ch<=2000;ch+=31){
  fit_layout(cw,ch,1280,960);int w=D(0x1d1d098),h=D(0x1d1d09c);
  CHECK(w<=cw&&h<=ch);CHECK(abs(w*960-h*1280)<1280);
 }
 D(0x1d1d000)=1;D(0x1d1d00c)=0x12345000;D(0x1d1d010)=1280;D(0x1d1d014)=960;
 D(0x1d1d018)=42;D(0x1d0b000)=0x103;client=(RECT){0,0,1000,600};
 CHECK(display_proc((HWND)1,WM_PAINT,0,0)==0);
 CHECK(paints==1&&ends==1&&stretches==1&&fills==2);
 CHECK(dst[0]==100&&dst[1]==0&&dst[2]==800&&dst[3]==600);
 CHECK(src[0]==1280&&src[1]==960&&D(0x1d1d018)==42);
 D(0x1d0b000)=0x13;D(0x1d1d010)=320;D(0x1d1d014)=200;
 display_proc((HWND)1,WM_PAINT,0,0);
 CHECK(dst[2]==800&&dst[3]==600&&src[0]==320&&src[1]==200);
 D(0x1d1d00c)=0;display_proc((HWND)1,WM_PAINT,0,0);
 CHECK(stretches==2&&paints==3&&ends==3);
 CHECK(display_proc((HWND)1,WM_ERASEBKGND,0,0)==1&&forwards==0);
 CHECK(display_proc((HWND)1,WM_SIZE,0,0)==85&&forwards==1);
 puts("Display geometry, paint lifecycle, VGA aspect, frame counter and message forwarding passed.");
 return 0;
}
