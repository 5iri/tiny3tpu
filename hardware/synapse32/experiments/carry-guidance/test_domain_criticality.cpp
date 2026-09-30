#include "domain_criticality.h"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
int main() {
    struct Domain { int slack, worst, maximum; };
    std::array<Domain,3> domains{{{-2000,-2000,12000},{2000,-500,9000},{1000,-1000,8000}}};
    std::array<int,3> order{{0,1,2}};
    int permutations=0;
    do {
        int slack=std::numeric_limits<int>::max();float criticality=0;
        for(int i:order) {auto d=domains[i];slack=tinyMergeSlack(slack,d.slack);criticality=tinyMergeCriticality(criticality,d.slack,d.worst,d.maximum);}
        assert(slack==-2000 && criticality==1.0f);++permutations;
    } while(std::next_permutation(order.begin(),order.end()));
    assert(permutations==6);
    // Single-domain behavior matches the original calculation across boundary cases.
    for(int maximum:{1,100,10000}) for(int worst:{-10000,-1,0,100}) for(int slack:{-10000,-100,0,100,10000}) {
        float old=std::min<double>(1.0,std::max<double>(0.0,1.0f-((float(slack)-float(worst))/maximum)));
        assert(tinyMergeCriticality(0,float(slack),float(worst),float(maximum))==old);
    }
    assert(tinyMergeCriticality(.5f,0,0,0)==.5f);
    assert(tinyMergeCriticality(.9f,100,0,100)==.9f);
    // Legacy last-domain assignment loses the violating domain in order 0,1.
    float legacy=1.0f-((float(domains[1].slack)-float(domains[1].worst))/domains[1].maximum);
    assert(legacy<1.0f);
    std::puts("PASS: domain-order invariance, worst slack retention, single-domain identity, zero range guard");
}
