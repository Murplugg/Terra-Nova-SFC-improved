.intel_syntax noprefix
.text
.globl _tn_original
_tn_original:
 push ebx
 push esi
 push edi
 push ebp
 mov eax,[esp+20]
 push DWORD PTR [esp+32]
 push DWORD PTR [esp+32]
 push DWORD PTR [esp+32]
 call eax
 add esp,12
 pop ebp
 pop edi
 pop esi
 pop ebx
 ret
