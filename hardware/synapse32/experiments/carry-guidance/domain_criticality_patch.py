"""Opt-in correction of per-user slack/criticality aggregation across domains."""
def patch(source,header):
 old='''        if (net_crit) {
            NPNR_ASSERT(crit_path);'''
 new='''        if (net_crit) {
            const bool tiny_domain_criticality = std::getenv("TINY3TPU_DOMAIN_CRITICALITY") != nullptr;
            NPNR_ASSERT(crit_path);'''
 assert source.count(old)==1;source=source.replace(old,new)
 old='                        nc.slack.at(i) = slack;'
 new='                        nc.slack.at(i) = tiny_domain_criticality ? tinyMergeSlack(nc.slack.at(i), slack) : slack;'
 assert source.count(old)==1;source=source.replace(old,new)
 old='''                        float criticality =
                                1.0f - ((float(nc.slack.at(i)) - float(worst_slack.at(startdomain.first))) / dmax);
                        nc.criticality.at(i) = std::min<double>(1.0, std::max<double>(0.0, criticality));'''
 new='''                        if (tiny_domain_criticality) {
                            const auto domain_slack = nd.min_required.at(i) -
                                    (nd.max_arrival + ctx->getNetinfoRouteDelay(net, net->users.at(i)));
                            nc.criticality.at(i) = tinyMergeCriticality(nc.criticality.at(i),
                                    float(domain_slack), float(worst_slack.at(startdomain.first)), float(dmax));
                        } else {
                            float criticality =
                                    1.0f - ((float(nc.slack.at(i)) - float(worst_slack.at(startdomain.first))) / dmax);
                            nc.criticality.at(i) = std::min<double>(1.0, std::max<double>(0.0, criticality));
                        }'''
 assert source.count(old)==1;source=source.replace(old,new)
 old='''                    nc.max_path_length = nd.max_path_length;
                    nc.cd_worst_slack = worst_slack.at(startdomain.first);'''
 new='''                    nc.max_path_length = tiny_domain_criticality ? std::max(nc.max_path_length, nd.max_path_length) : nd.max_path_length;
                    nc.cd_worst_slack = tiny_domain_criticality ? tinyMergeSlack(nc.cd_worst_slack, worst_slack.at(startdomain.first)) : worst_slack.at(startdomain.first);'''
 assert source.count(old)==1;source=source.replace(old,new)
 return source.replace('#include "timing.h"',f'#include "timing.h"\n#include <cstdlib>\n#include "{header}"',1)
