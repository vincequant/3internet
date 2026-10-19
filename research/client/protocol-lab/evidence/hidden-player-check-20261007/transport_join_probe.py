"""One ordinary transport join to the user's own waiting room; no game handshake."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import json,time,hashlib,struct,os
assert c.sizeof(c.c_void_p)==4
assert Path(os.environ['WINEPREFIX']).name=='prefix-sikarugir10'
root=Path(r'C:\sgi\run-3.5');os.chdir(str(root));dllpath=root/'3I/Koeinm.dll'
assert hashlib.sha256(dllpath.read_bytes()).hexdigest()=='629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841'
assert hashlib.sha256((root/'NetHookCore.dll').read_bytes()).hexdigest()=='5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4'
u=c.WinDLL('user32');u.PeekMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT];u.TranslateMessage.argtypes=[c.POINTER(w.MSG)];u.DispatchMessageW.argtypes=[c.POINTER(w.MSG)]
k=c.WinDLL('kernel32');k.GlobalFree.argtypes=[c.c_void_p]
msg=w.MSG();u.PeekMessageW(c.byref(msg),None,0,0,0)
dll=c.WinDLL(str(dllpath));hook=c.WinDLL(str(root/'NetHookCore.dll'))
def export(name,args,restype=c.c_int):
 f=getattr(dll,name);f.argtypes=args;f.restype=restype;return f
start=export('_NetMsg_Start@36',[c.c_uint32]*8+[c.POINTER(c.c_uint32)])
search=export('_NetMsg_SearchSession@12',[c.c_char_p,w.HWND,w.UINT])
getip=export('_NetMsg_GetIPAddress@4',[c.POINTER(c.c_void_p)])
opens=export('_NetMsg_OpenSession@20',[c.c_char_p,c.c_char_p,c.c_char_p,c.c_uint32,c.c_uint32])
connected=export('_NetMsg_IsConnected@0',[])
setdata=export('_NetMsg_SetDataWindow@8',[w.HWND,w.UINT])
exit_session=export('_NetMsg_ExitSession@0',[]);end=export('_NetMsg_End@0',[])
flag=c.c_uint32();rc=start(8,64,7777,100,100,78731,0,0,c.byref(flag));print(json.dumps({'stage':'start','rc':rc,'windows_version':list(__import__('sys').getwindowsversion())}),flush=True)
assert rc==0
base=dll._handle+0x12170
rooms=[]
def snapshot(stage):
 count=c.c_uint32.from_address(base+0x43bc).value;assert count<=8
 ptr=c.c_uint32.from_address(base+0x43b8).value
 members=[]
 for i in range(count):
  raw=c.string_at(ptr+i*0x164,35);members.append({'id':str(struct.unpack_from('<I',raw)[0]),'name':raw[4:35].split(b'\0')[0].decode('gbk','replace')})
 print(json.dumps({'stage':stage,'connected':connected(),'members':members,'count':count},ensure_ascii=False),flush=True)
try:
 ip_ptr=c.c_void_p();ip_count=getip(c.byref(ip_ptr));assert 0<ip_count<=20 and ip_ptr.value
 addresses=list((c.c_uint32*ip_count).from_address(ip_ptr.value));print(json.dumps({'stage':'resolved_addresses','addresses':['.'.join(str(x) for x in struct.pack('!I',v)) for v in addresses]}),flush=True)
 # Use the original DLL's observed local address, matching the normal running client.
 own=addresses[0];ownip='.'.join(str(x) for x in struct.pack('!I',own));assert ownip=='10.228.84.151' and own!=176202538
 print(json.dumps({'stage':'original_transport_identity','local_ip':ownip,'id':str(own),'matches_original_client':True}),flush=True)
 rc=search(b'10.128.163.42',None,0x2461)
 while u.PeekMessageW(c.byref(msg),None,0x2461,0x2461,1):
  if msg.wParam==5 and msg.lParam:
   raw=c.string_at(msg.lParam,80);room={'id':str(struct.unpack_from('<I',raw)[0]),'name':raw[4:35].split(b'\0')[0].decode('gbk','replace'),'host':raw[35:66].split(b'\0')[0].decode('gbk','replace')};rooms.append(room);k.GlobalFree(msg.lParam)
 print(json.dumps({'stage':'search','rc':rc,'rooms':rooms},ensure_ascii=False),flush=True)
 assert not rooms or any(r['id']=='176202538' and r['name']=='SGZWLB' and r['host']=='kwankwan' for r in rooms),'Target mismatch; no join attempted'
 print(json.dumps({'stage':'target_binding','primary_client_room':'SGZWLB[kwankwan]','host_read_only_identity':'176202538','target':'10.128.163.42','own_probe_reply_verified':bool(rooms)}),flush=True)
 setdata(None,0x2462)
 rc=opens(b'10.128.163.42',b'SGZWLB','VK(筑基期)'.encode('gbk'),own,3000)
 print(json.dumps({'stage':'open_session','rc':rc,'only_transport_handshake':True}),flush=True);snapshot('after_join')
 if rc==0:
  deadline=time.monotonic()+90;last=0
  while time.monotonic()<deadline:
   while u.PeekMessageW(c.byref(msg),None,0,0,1):
    if msg.message==0x2462:print(json.dumps({'stage':'network_notification','wparam':int(msg.wParam),'has_lparam':bool(msg.lParam)}),flush=True)
    else:u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
   if time.monotonic()-last>=5:snapshot('held_connection');last=time.monotonic()
   time.sleep(.05)
finally:
 print(json.dumps({'stage':'cleanup','exit_rc':exit_session(),'end_rc':end()}),flush=True)
