"""Preserve both combinational fanin and clock origins on mixed RAM outputs."""
def patch(source):
    old='''                if (portClass == TMG_REGISTER_OUTPUT) {
                    topographical_order.emplace_back(o->net);'''
    new='''                if (portClass == TMG_REGISTER_OUTPUT || (portClass == TMG_COMB_OUTPUT && clocks > 0)) {
                    // Mixed outputs are queued only after their read fanin is ready.
                    if (portClass == TMG_REGISTER_OUTPUT)
                        topographical_order.emplace_back(o->net);'''
    assert source.count(old)==1
    result=source.replace(old,new)
    old='''
                } else {
                    if (portClass == TMG_STARTPOINT || portClass == TMG_GEN_CLOCK || portClass == TMG_IGNORE) {'''
    new='''
                }
                if (portClass != TMG_REGISTER_OUTPUT) {
                    if (portClass == TMG_STARTPOINT || portClass == TMG_GEN_CLOCK || portClass == TMG_IGNORE) {'''
    assert result.count(old)==1;result=result.replace(old,new)
    old='''                    if (!port_fanin.count(o) && !net_data.count(o->net)) {
                        topographical_order.emplace_back(o->net);'''
    new='''                    if (!port_fanin.count(o) && portClass == TMG_COMB_OUTPUT && clocks > 0) {
                        topographical_order.emplace_back(o->net);
                    } else if (!port_fanin.count(o) && !net_data.count(o->net)) {
                        topographical_order.emplace_back(o->net);'''
    assert result.count(old)==1;result=result.replace(old,new)
    old='''                    delay_t max_arrival = std::numeric_limits<delay_t>::min();
                    // Look at all input ports on its driving cell'''
    new='''                    delay_t max_arrival = std::numeric_limits<delay_t>::min();
                    int origin_clocks = 0;
                    auto origin_class = ctx->getPortTimingClass(crit_net->driver.cell, crit_net->driver.port, origin_clocks);
                    if (origin_class == TMG_COMB_OUTPUT && origin_clocks > 0) {
                        for (int i = 0; i < origin_clocks; ++i) {
                            auto ci = ctx->getPortClockingInfo(crit_net->driver.cell, crit_net->driver.port, i);
                            auto cn = get_net_or_empty(crit_net->driver.cell, ci.clock_port);
                            ClockEvent ev{cn ? cn->name : async_clock, cn ? ci.edge : RISING_EDGE};
                            if (ev == crit_pair.first.start)
                                max_arrival = std::max(max_arrival, ci.clockToQ.maxDelay());
                        }
                    }
                    // Look at all input ports on its driving cell'''
    assert result.count(old)==1;result=result.replace(old,new)
    old='''            if (portClass == TMG_REGISTER_OUTPUT) {
                for (int i = 0; i < port_clocks; i++) {'''
    new='''            if (portClass == TMG_REGISTER_OUTPUT || (portClass == TMG_COMB_OUTPUT && port_clocks > 0)) {
                for (int i = 0; i < port_clocks; i++) {'''
    assert result.count(old)==1;result=result.replace(old,new)
    return result
