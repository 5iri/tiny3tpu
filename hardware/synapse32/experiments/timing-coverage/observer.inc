// Read-only observation of the live routed graph. No timing model overrides.
static void tiny3tpu_export_timing_graph(Context *ctx)
{
    const char *path = getenv("TINY3TPU_TIMING_GRAPH");
    if (!path) return;
    FILE *f = fopen(path, "w");
    if (!f) log_error("Cannot open timing graph export %s\n", path);
    fprintf(f, "VERSION\t1\n");
    for (const auto &entry : ctx->cells) {
        const auto *cell = entry.second.get();
        for (const auto &p : cell->ports) {
            if (!p.second.net) continue;
            int count = 0;
            auto cls = ctx->getPortTimingClass(cell, p.first, count);
            fprintf(f, "PORT\t%s\t%s\t%s\t%s\t%d\t%d\t%s\n",
                    cell->name.c_str(ctx), cell->type.c_str(ctx), p.first.c_str(ctx),
                    p.second.type == PORT_IN ? "input" : p.second.type == PORT_OUT ? "output" : "inout",
                    int(cls), count, p.second.net->name.c_str(ctx));
            for (int i = 0; i < count; ++i) {
                auto c = ctx->getPortClockingInfo(cell, p.first, i);
                fprintf(f, "CLOCK\t%s\t%s\t%d\t%s\t%d\t%.9f\t%.9f\t%.9f\n",
                        cell->name.c_str(ctx), p.first.c_str(ctx), i, c.clock_port.c_str(ctx), int(c.edge),
                        ctx->getDelayNS(c.setup.maxDelay()), ctx->getDelayNS(c.hold.maxDelay()),
                        ctx->getDelayNS(c.clockToQ.maxDelay()));
            }
            if (p.second.type != PORT_IN) continue;
            for (const auto &o : cell->ports) {
                if (o.second.type != PORT_OUT || !o.second.net) continue;
                DelayInfo d;
                if (ctx->getCellDelay(cell, p.first, o.first, d))
                    fprintf(f, "CELLARC\t%s\t%s\t%s\t%.9f\n", cell->name.c_str(ctx),
                            p.first.c_str(ctx), o.first.c_str(ctx), ctx->getDelayNS(d.maxDelay()));
            }
        }
    }
    for (const auto &entry : ctx->nets) {
        auto *net = entry.second.get();
        if (!net->driver.cell) continue;
        for (const auto &u : net->users)
            fprintf(f, "NETARC\t%s\t%s\t%s\t%s\t%s\t%.9f\n", net->name.c_str(ctx),
                    net->driver.cell->name.c_str(ctx), net->driver.port.c_str(ctx),
                    u.cell->name.c_str(ctx), u.port.c_str(ctx), ctx->getDelayNS(ctx->getNetinfoRouteDelay(net, u)));
    }
    if (ferror(f)) log_error("Timing graph export write failed\n");
    if (fclose(f)) log_error("Timing graph export close failed\n");
    log_info("TIMING_GRAPH_EXPORTED %s\n", path);
}
