"""Exact gj calculator arithmetic; callers explicitly supply armament and ability."""
import math

PARAMETERS = {
    '步兵': (50,100,(0,100,200)), '生步兵': (50,100,(0,100,200)),
    '强化步兵': (150,40,(0,100,200)), '重装步兵': (190,40,(0,100,200)),
    '骑兵': (100,50,(0,150,350)), '生骑兵': (100,50,(0,150,350)),
    '强化骑兵': (150,50,(0,150,350)),
    '重装骑兵': (200,50,(0,150,350)), '铁骑兵': (200,50,(0,150,350)),
}

def factor(kind, size, armament):
    if kind not in PARAMETERS or type(size) is not int or size not in (0,1,2):
        return None
    if type(armament) is not int or not 0 <= armament <= 300:
        return None
    base, coefficient, sizes = PARAMETERS[kind]
    return base + sizes[size] + math.floor(coefficient*armament/100+.5)

def attack(kind, size, armament, ability):
    total = factor(kind,size,armament)
    if total is None or type(ability) is not int or not 0 <= ability <= 150:
        return None
    return math.floor(ability*total/150+.5)
