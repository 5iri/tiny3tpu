PipId Arch::getPipByName(IdString name) const
{
    if (pip_by_name_cache.count(name))
        return pip_by_name_cache.at(name);
    setup_byname();
    const std::string &serialized = name.str(this);
    auto context = serialized.find("@DST=");
    const std::string s = serialized.substr(0, context);
    WireId expected_dst;
    if (context != std::string::npos) {
        expected_dst = getWireByName(id(serialized.substr(context + 5)));
        if (expected_dst == WireId()) log_error("Unknown routing destination.\n");
    }
    PipId ret;
    int matches = 0;
    auto accept = [&](PipId pip) {
        if (getPipName(pip) == id(s) &&
            (context == std::string::npos || getPipDstWire(pip) == expected_dst)) {
            ret = pip;
            ++matches;
        }
    };
    auto arrow = s.find("->");
    if (arrow != std::string::npos) {
        WireId src = getWireByName(id(s.substr(0, arrow)));
        WireId dst = getWireByName(id(s.substr(arrow + 2)));
        if (src == WireId() || dst == WireId())
            log_error("Unknown wire in serialized pip '%s'.\n", s.c_str());
        for (auto pip : getPipsDownhill(src))
            if (getPipDstWire(pip) == dst)
                accept(pip);
    } else if (s.substr(0, 8) == "SITEPIP/") {
        auto parts = split_identifier_name(s.substr(8));
        int tile, site;
        std::tie(tile, site) = site_by_name.at(parts.first);
        const auto &info = chip_info->tile_types[chip_info->tile_insts[tile].type];
        auto bp = split_identifier_name(parts.second);
        IdString bel = id(bp.first), pin = id(bp.second);
        for (int i = 0; i < info.num_pips; ++i) {
            const auto &p = info.pip_data[i];
            if (p.site == site && p.bel == bel.index) {
                PipId candidate; candidate.tile = tile; candidate.index = i;
                accept(candidate);
            }
        }
        // Preserve legacy site-pin spelling if it is not an exported name.
        if (matches == 0 && context == std::string::npos) {
            for (int i = 0; i < info.num_pips; ++i) {
                const auto &p = info.pip_data[i];
                if (p.site == site && p.bel == bel.index && p.extra_data == pin.index) {
                    ret.tile = tile; ret.index = i; ++matches;
                }
            }
        }
    } else {
        // Legacy tile/numeric-source.numeric-destination spelling.
        auto parts = split_identifier_name(s);
        int tile = tile_by_name.at(parts.first);
        const auto &info = chip_info->tile_types[chip_info->tile_insts[tile].type];
        auto wires = split_identifier_name_dot(parts.second);
        int src = std::stoi(wires.first), dst = std::stoi(wires.second);
        for (int i = 0; i < info.num_pips; ++i) {
            const auto &p = info.pip_data[i];
            if (p.site == -1 && p.src_index == src && p.dst_index == dst) {
                ret.tile = tile; ret.index = i; ++matches;
            }
        }
    }
    if (matches != 1)
        log_error("Serialized pip '%s' resolves to %d resources; refusing ambiguous or missing routing.\n", s.c_str(), matches);
    pip_by_name_cache[name] = ret;
    return ret;
}
