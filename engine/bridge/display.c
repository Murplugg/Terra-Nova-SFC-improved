/* GDI presentation: integer enlargement and proportional fitting below native size. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#define API __declspec(dllexport)
#ifndef D
#define D(a) (*(volatile uint32_t *)(uintptr_t)(a))
#endif
/* Windows dispatches paint messages inside its modal resize loop, while the
   game's normal pump is suspended. Redraw its prepared frame without advancing
   simulation, audio, or the presented-frame counter. */
#ifndef TN_GAME_WINDOW_PROC
#define TN_GAME_WINDOW_PROC ((WNDPROC)(uintptr_t)0x1d19800)
#endif
static LRESULT CALLBACK display_proc(HWND, UINT, WPARAM, LPARAM);
static const DWORD style=WS_OVERLAPPEDWINDOW|WS_VISIBLE;
static RECT bounds_for(UINT dpi){RECT r={0,0,800,600};AdjustWindowRectExForDpi(&r,style,FALSE,0,dpi);return r;}
API void TN_MinMax(HWND h,MINMAXINFO *m){
 UINT dpi=GetDpiForWindow(h);RECT r=bounds_for(dpi?dpi:96);
 m->ptMinTrackSize.x=r.right-r.left;m->ptMinTrackSize.y=r.bottom-r.top;
}
API uint32_t TN_NewWindow(void){
 if(!SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))return 0;
 HWND old=(HWND)(uintptr_t)D(0x1d1d000);RECT where={80,80,900,730};if(old)GetWindowRect(old,&where);
 HINSTANCE inst=GetModuleHandleA(0);WNDCLASSEXA wc={0};wc.cbSize=sizeof(wc);wc.style=CS_HREDRAW|CS_VREDRAW;
 wc.lpfnWndProc=display_proc;wc.hInstance=inst;wc.hbrBackground=GetStockObject(BLACK_BRUSH);wc.lpszClassName="TNHRNativeResearch31";
 if(!RegisterClassExA(&wc) && GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)return 0;
 HWND h=CreateWindowExA(0,wc.lpszClassName,"Terra Nova - native Windows research 31 (PCM audio)",style,where.left,where.top,820,649,0,0,inst,0);
 if(!h)return 0;
 RECT r=bounds_for(GetDpiForWindow(h));
 SetWindowPos(h,0,where.left,where.top,r.right-r.left,r.bottom-r.top,SWP_NOZORDER|SWP_NOACTIVATE);
 D(0x1d1d000)=(uint32_t)(uintptr_t)h;
 if(old)DestroyWindow(old); /* The window procedure ignores old-window destroy. */
 return (uint32_t)(uintptr_t)h;
}
static void fit_layout(int cw,int ch,int w,int h){
 int dw=0,dh=0;
 if(cw>0&&ch>0&&w>0&&h>0){
  if(cw>=w&&ch>=h){
   int sx=cw/w,sy=ch/h,k=sx<sy?sx:sy;dw=w*k;dh=h*k;
  }else if((int64_t)cw*h<=(int64_t)ch*w){
   dw=cw;dh=(int)((int64_t)cw*h/w);
  }else{
   dh=ch;dw=(int)((int64_t)ch*w/h);
  }
 }
 D(0x1d1d098)=dw;D(0x1d1d09c)=dh;
 D(0x1d1d090)=cw>dw?(cw-dw)/2:0;
 D(0x1d1d094)=ch>dh?(ch-dh)/2:0;
}
API void TN_Layout(void){
 fit_layout(D(0x1d1d248),D(0x1d1d24c),D(0x1d1d010),D(0x1d1d014));
}
API void TN_ClearBars(HDC dc){
 int x=D(0x1d1d090),y=D(0x1d1d094),w=D(0x1d1d098),h=D(0x1d1d09c),cw=D(0x1d1d248),ch=D(0x1d1d24c);
 RECT bars[4]={{0,0,cw,y},{0,y+h,cw,ch},{0,y,x,y+h},{x+w,y,cw,y+h}};
 HBRUSH black=GetStockObject(BLACK_BRUSH);
 for(int i=0;i<4;i++)if(bars[i].right>bars[i].left&&bars[i].bottom>bars[i].top)FillRect(dc,&bars[i],black);
}

static void paint_frame(HWND h){
 PAINTSTRUCT ps;
 HDC dc=BeginPaint(h,&ps);
 if(!dc)return;
 RECT r;
 if(GetClientRect(h,&r)){
  int w=D(0x1d1d010),height=D(0x1d1d014);
  if(h==(HWND)(uintptr_t)D(0x1d1d000)&&D(0x1d1d00c)&&w>0&&height>0){
   D(0x1d1d248)=r.right;D(0x1d1d24c)=r.bottom;
   /* VGA movies retain the same 4:3 display correction as the regular pump. */
   int vga=D(0x1d0b000)==0x13;
   fit_layout(r.right,r.bottom,vga?800:w,vga?600:height);
   TN_ClearBars(dc);
   SetStretchBltMode(dc,COLORONCOLOR);
   StretchDIBits(dc,D(0x1d1d090),D(0x1d1d094),D(0x1d1d098),D(0x1d1d09c),
                0,0,w,height,(const void *)(uintptr_t)D(0x1d1d00c),
                (const BITMAPINFO *)(uintptr_t)0x1d1d400,DIB_RGB_COLORS,SRCCOPY);
  }else{
   FillRect(dc,&r,GetStockObject(BLACK_BRUSH));
  }
 }
 EndPaint(h,&ps);
}
static LRESULT CALLBACK display_proc(HWND h,UINT msg,WPARAM wp,LPARAM lp){
 if(msg==WM_PAINT){paint_frame(h);return 0;}
 if(msg==WM_ERASEBKGND)return 1; /* WM_PAINT fills both the image and its bars. */
 return CallWindowProcA(TN_GAME_WINDOW_PROC,h,msg,wp,lp);
}
