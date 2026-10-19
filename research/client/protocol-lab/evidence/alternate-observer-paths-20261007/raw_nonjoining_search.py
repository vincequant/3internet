"""Nonjoining search/listen control; only explicit user-owned room, normal transport."""
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
cmdcount=export('_NetMsg_GetCmdCount@0',[])
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
 print(json.dumps({'stage':stage,'connected':connected(),'members':members,'count':count,'cached_commands':cmdcount()},ensure_ascii=False),flush=True)
try:
 ip_ptr=c.c_void_p();ip_count=getip(c.byref(ip_ptr));assert 0<ip_count<=20 and ip_ptr.value
 addresses=list((c.c_uint32*ip_count).from_address(ip_ptr.value));print(json.dumps({'stage':'resolved_addresses','addresses':['.'.join(str(x) for x in struct.pack('!I',v)) for v in addresses]}),flush=True)
 # Use the original DLL's observed local address, matching the normal running client.
 own=addresses[0];ownip='.'.join(str(x) for x in struct.pack('!I',own));assert ownip=='10.228.84.151' and own!=176202538
 print(json.dumps({'stage':'original_transport_identity','local_ip':ownip,'id':str(own),'matches_original_client':True}),flush=True)
 class SockAddr(c.Structure):
  _fields_=[('family',c.c_ushort),('port',c.c_ushort),('ip',c.c_uint32),('padding',c.c_char*8)]
 ws=c.WinDLL('ws2_32');ws.socket.argtypes=[c.c_int,c.c_int,c.c_int];ws.socket.restype=c.c_uint32
 ws.bind.argtypes=[c.c_uint32,c.c_void_p,c.c_int];ws.setsockopt.argtypes=[c.c_uint32,c.c_int,c.c_int,c.c_void_p,c.c_int]
 ws.getsockname.argtypes=[c.c_uint32,c.c_void_p,c.POINTER(c.c_int)]
 ws.sendto.argtypes=[c.c_uint32,c.c_void_p,c.c_int,c.c_int,c.c_void_p,c.c_int]
 ws.recvfrom.argtypes=[c.c_uint32,c.c_void_p,c.c_int,c.c_int,c.c_void_p,c.POINTER(c.c_int)]
 sock=ws.socket(2,2,17);assert sock!=0xffffffff
 try:
  local=SockAddr();local.family=2;assert ws.bind(sock,c.byref(local),16)==0
  timeout=c.c_uint32(2500);assert ws.setsockopt(sock,0xffff,0x1006,c.byref(timeout),4)==0
  n=c.c_int(16);assert ws.getsockname(sock,c.byref(local),c.byref(n))==0
  import socket as pysocket
  dst=SockAddr();dst.family=2;dst.port=pysocket.htons(7777);dst.ip=struct.unpack('<I',pysocket.inet_aton('10.128.163.42'))[0]
  raw=struct.pack('!I',78731);buf=c.create_string_buffer(raw)
  sent=ws.sendto(sock,buf,len(raw),0,c.byref(dst),16)
  print(json.dumps({'stage':'one_exact_discovery_datagram','sent':sent,'local_port':pysocket.ntohs(local.port),'target':'10.128.163.42:7777','no_join':True}),flush=True)
  assert sent==4
  received=c.create_string_buffer(2048);peer=SockAddr();n=c.c_int(16)
  size=ws.recvfrom(sock,received,2048,0,c.byref(peer),c.byref(n))
  result={'stage':'discovery_response','bytes':size,'error':ws.WSAGetLastError() if size<0 else 0}
  if size==78:
   data=received.raw[:size];hostid=struct.unpack_from('!I',data)[0];name=data[4:35].split(b'\0')[0].decode('gbk','replace');host=data[35:66].split(b'\0')[0].decode('gbk','replace')
   assert hostid==176202538 and name=='SGZWLB' and host=='kwankwan'
   result['room']={'id':str(hostid),'name':name,'host':host,'maximum':struct.unpack_from('!I',data,66)[0],'current':struct.unpack_from('!I',data,70)[0]}
  print(json.dumps(result,ensure_ascii=False),flush=True);snapshot('unjoined_after_raw_query')
 finally:ws.closesocket(sock)

finally:
 print(json.dumps({'stage':'cleanup','end_rc':end()}),flush=True)
