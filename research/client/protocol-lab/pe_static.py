"""Small bounded PE reader for static protocol research; executes no target code."""
from pathlib import Path
import struct
import subprocess


class PE:
    def __init__(self, path):
        self.path=Path(path);self.data=self.path.read_bytes()
        pe=struct.unpack_from('<I',self.data,60)[0];opt=pe+24
        self.base=struct.unpack_from('<I',self.data,opt+28)[0]
        sec=opt+struct.unpack_from('<H',self.data,pe+20)[0]
        self.sections=[struct.unpack_from('<IIII',self.data,sec+i*40+8)
                       for i in range(struct.unpack_from('<H',self.data,pe+6)[0])]
    def offset(self,va):
        r=va-self.base
        for vs,v,sz,raw in self.sections:
            if v<=r<v+sz:return raw+r-v
        raise ValueError(hex(va))
    def va(self,offset):
        for vs,v,sz,raw in self.sections:
            if raw<=offset<raw+sz:return self.base+v+offset-raw
        raise ValueError(offset)
    def read(self,va,n):
        i=self.offset(va);return self.data[i:i+n]
    def u32(self,va):return struct.unpack('<I',self.read(va,4))[0]
    def words(self,va,n):
        for a in range(va,va+n,4):print(hex(a),hex(self.u32(a)))
    def dis(self,va,n):
        return subprocess.check_output(['/usr/bin/objdump','-d',
             '--start-address='+hex(va),'--stop-address='+hex(va+n),str(self.path)],text=True)
    def refs(self,va):
        token=struct.pack('<I',va);start=0;result=[]
        while True:
            at=self.data.find(token,start)
            if at<0:return result
            result.append(self.va(at));start=at+1
    def calls(self,va):
        result=[]
        for vs,v,sz,raw in self.sections:
            if v != 0x1000:continue
            for i in range(raw,raw+sz-5):
                if self.data[i] not in (0xe8,0xe9):continue
                a=self.va(i)
                if a+5+struct.unpack_from('<i',self.data,i+1)[0]==va:result.append(a)
        return result


if __name__=='__main__':
    import sys
    pe=PE(sys.argv[1]);a=int(sys.argv[3],0);n=int(sys.argv[4],0) if len(sys.argv)>4 else 256
    if sys.argv[2]=='dis':print(pe.dis(a,n))
    elif sys.argv[2]=='words':pe.words(a,n)
    elif sys.argv[2]=='refs':print([hex(x) for x in pe.refs(a)])
    elif sys.argv[2]=='calls':print([hex(x) for x in pe.calls(a)])
