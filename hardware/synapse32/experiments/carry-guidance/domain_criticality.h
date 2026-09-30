#pragma once
#include <algorithm>
#include <limits>
template <typename T> inline T tinyMergeSlack(T old_value, T domain_value)
{
    return std::min(old_value, domain_value);
}
inline float tinyMergeCriticality(float old_value, float domain_slack, float domain_worst, float domain_max)
{
    if (domain_max <= 0) return old_value;
    float value = 1.0f - ((domain_slack - domain_worst) / domain_max);
    return std::max(old_value, float(std::min<double>(1.0, std::max<double>(0.0, value))));
}
