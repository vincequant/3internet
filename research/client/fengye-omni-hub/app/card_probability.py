"""Finite, unequal card multiplicities: sampling without replacement."""
from math import comb
from fractions import Fraction
from native_diplomacy import WHITE_IDS

def distribution(total,successes,draws):
 if any(type(x) is not int for x in (total,successes,draws)) or not 0<=successes<=total or not 0<=draws<=total:raise ValueError('抽牌数与卡池数量不符')
 denom=comb(total,draws)
 return [Fraction(comb(successes,k)*comb(total-successes,draws-k),denom) if 0<=k<=successes and 0<=draws-k<=total-successes else Fraction(0) for k in range(draws+1)]
def probability_rows(counts,draws,names):
 if set(counts)!=set(range(1,29)) or any(type(n) is not int or n<0 for n in counts.values()):raise ValueError('需提供完整28类卡池数量')
 total=sum(counts.values());groups=[('白卡（全部）',WHITE_IDS),('宣战卡（含废弃宣战）',{1,6}),('停战卡',{2}),('拒绝卡（不含斩使）',{8,9})]
 groups += [(names.get(str(i),str(i)),{i}) for i in range(1,29)]
 result=[]
 for name,ids in groups:
  available=sum(counts[i] for i in ids);dist=distribution(total,available,draws)
  result.append(dict(name=name,available=available,total=total,draws=draws,at_least_one=1-dist[0],expected=Fraction(draws*available,total) if total else Fraction(0),distribution=dist))
 return result
