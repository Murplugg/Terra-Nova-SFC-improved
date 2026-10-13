/* Integer pixel presentation in a per-monitor-DPI-aware game window. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#define API __declspec(dllexport)
#ifndef D
#define D(a) (*(volatile uint32_t *)(uintptr_t)(a))
#endif
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
 wc.lpfnWndProc=(WNDPROC)(uintptr_t)0x1d19800;wc.hInstance=inst;wc.hbrBackground=GetStockObject(BLACK_BRUSH);wc.lpszClassName="TNHRNativeResearch31";
 if(!RegisterClassExA(&wc) && GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)return 0;
 HWND h=CreateWindowExA(0,wc.lpszClassName,"Terra Nova - native Windows research 31 (PCM audio)",style,where.left,where.top,820,649,0,0,inst,0);
 if(!h)return 0;
 RECT r=bounds_for(GetDpiForWindow(h));
 SetWindowPos(h,0,where.left,where.top,r.right-r.left,r.bottom-r.top,SWP_NOZORDER|SWP_NOACTIVATE);
 D(0x1d1d000)=(uint32_t)(uintptr_t)h;
 if(old)DestroyWindow(old); /* The window procedure ignores old-window destroy. */
 return (uint32_t)(uintptr_t)h;
}
API void TN_Layout(void){
 int cw=D(0x1d1d248),ch=D(0x1d1d24c),w=D(0x1d1d010),h=D(0x1d1d014);
 if(w<1||h<1)return;
 int sx=cw/w,sy=ch/h,k=sx<sy?sx:sy;if(k<1)k=1;
 D(0x1d1d098)=w*k;D(0x1d1d09c)=h*k;
 D(0x1d1d090)=cw>w*k?(cw-w*k)/2:0;D(0x1d1d094)=ch>h*k?(ch-h*k)/2:0;
}
API void TN_ClearBars(HDC dc){
 int x=D(0x1d1d090),y=D(0x1d1d094),w=D(0x1d1d098),h=D(0x1d1d09c),cw=D(0x1d1d248),ch=D(0x1d1d24c);
 RECT bars[4]={{0,0,cw,y},{0,y+h,cw,ch},{0,y,x,y+h},{x+w,y,cw,y+h}};
 HBRUSH black=GetStockObject(BLACK_BRUSH);
 for(int i=0;i<4;i++)if(bars[i].right>bars[i].left&&bars[i].bottom>bars[i].top)FillRect(dc,&bars[i],black);
}
