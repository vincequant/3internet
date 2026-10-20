from probe import *
def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def string(m,a):
    if a<0x10000:return None
    b=m.read(a,64)
    if not b:return None
    try:return b.split(b'\0')[0].decode('gbk')
    except UnicodeDecodeError:return None
def main():
    m=Memory();t=time.perf_counter()
    try:
        m.load();hits=m.find(struct.pack('<I',0x5056f0),10000);rows=[]
        for a in hits:
            if a<0x1000000:continue
            b=m.read(a,0xa0)
            if not b:continue
            names=[string(m,u32(b,o)) for o in (12,16,20,24)]
            rows.append({'addr':hex(a),'id_candidate':u16(b,10),'owner':u16(b,8),'name_parts':names,'name':''.join(n or '' for n in names[:2]),'birth_candidate':u16(b,30),'soldiers':u16(b,35),'attributes':list(b[37:42]),'u16':[u16(b,o) for o in range(0,0x60,2)],'hex':b.hex()})
        refs={}
        for a in [0x4b02bc0,0x4af9b60,0x4b11d00]+([int(rows[0]['addr'],16)] if rows else []):
            rr=m.find(struct.pack('<I',a),100)
            refs[hex(a)]=[m.context(x,32,64) for x in rr]
        out={'identity':m.identity,'readonly':True,'vtable_candidate':'0x5056f0','hits':len(hits),'rows':rows,'references':refs,'elapsed_s':time.perf_counter()-t}
        (ROOT/'officer_candidates.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        from collections import Counter
        print(json.dumps({'rows':len(rows),'owners':dict(Counter(r['owner'] for r in rows)),'samples':[{k:v for k,v in r.items() if k not in ('u16','hex')} for r in rows[:5]+[r for r in rows if r['owner']==11]],'refs':refs,'elapsed':out['elapsed_s']},ensure_ascii=False,indent=2))
    finally:m.close()
if __name__=='__main__':main()
