// DS182 v2.19 Table 35, maxima across all listed speed/voltage grades.
// Exact supported profile: PREG-only, direct A/B, multiply plus C, fixed mode.
static std::string preg_pin_base(const Arch *a, IdString p)
{
    std::string s = p.str(a);
    while (!s.empty() && s.back() >= '0' && s.back() <= '9') s.pop_back();
    return s;
}

static int preg_constant_pin(const Arch *a, const CellInfo *c, const std::string &pin)
{
    // pack_constants may replace a tied-low DSP input with the shared VCC
    // net and set IS_<bus>[bit]_INVERTED.  Inspect the effective logical
    // value, not the post-pack wire alone.
    std::size_t suffix = pin.size();
    while (suffix && pin[suffix - 1] >= '0' && pin[suffix - 1] <= '9') --suffix;
    std::string bus = pin.substr(0, suffix);
    std::string index = pin.substr(suffix);
    bool inverted = false;
    if (!index.empty()) {
        auto mask = c->params.find(a->id("IS_" + bus + "_INVERTED"));
        if (mask != c->params.end())
            inverted = ((mask->second.as_int64() >> std::stoi(index)) & 1) != 0;
    }
    auto bit = c->params.find(a->id("IS_" + (index.empty() ? bus : bus + "[" + index + "]") + "_INVERTED"));
    if (bit != c->params.end()) inverted |= bit->second.as_bool();
    auto net = get_net_or_empty(c, a->id(pin));
    if (net && net->driver.cell) {
        if (net->driver.cell->type == id_PSEUDO_GND) return inverted ? 1 : 0;
        if (net->driver.cell->type == id_PSEUDO_VCC) return inverted ? 0 : 1;
        // The router can realize an unreachable constant with an input-less
        // LUT. Recognize only an explicitly constant truth table;
        // accepting a net by its generated name would hide a dynamic mode pin.
        const auto *driver = net->driver.cell;
        if (driver->type == id_SLICE_LUTX && net->driver.port == id_O6) {
            auto init = driver->params.find(a->id("INIT"));
            bool no_inputs = true;
            for (const auto &port : driver->ports)
                if (port.second.type == PORT_IN && port.second.net) no_inputs = false;
            const auto original = str_or_default(driver->attrs, a->id("X_ORIG_TYPE"), "");
            const size_t width = original == "LUT1" ? 2 : 64;
            if (no_inputs && init != driver->params.end() && !init->second.is_string && init->second.str.size() == width) {
                const auto &bits = init->second.str;
                if (bits == std::string(width, Property::S0)) return inverted ? 1 : 0;
                if (bits == std::string(width, Property::S1)) return inverted ? 0 : 1;
            }
        }
        return -1;
    }
    for (int v = 0; v < 2; ++v) {
        auto key = a->id(v ? "DSP_VCC_PINS" : "DSP_GND_PINS");
        auto it = c->attrs.find(key);
        if (it != c->attrs.end() && (" " + it->second.as_string() + " ").find(" " + pin + " ") != std::string::npos)
            return v ^ int(inverted);
    }
    return -1;
}

static bool preg_timing_supported(const Arch *a, const CellInfo *c)
{
    auto p = c->params.find(a->id("PREG"));
    if (p == c->params.end() || p->second.as_int64() != 1) return false;
    for (const char *r : {"AREG", "BREG", "CREG", "DREG", "ADREG", "MREG", "ACASCREG", "BCASCREG",
                          "ALUMODEREG", "CARRYINREG", "CARRYINSELREG", "INMODEREG", "OPMODEREG"}) {
        auto it = c->params.find(a->id(r));
        if (it == c->params.end() || it->second.as_int64() != 0) return false;
    }
    for (auto pair : {std::make_pair("A_INPUT", "DIRECT"), std::make_pair("B_INPUT", "DIRECT"),
                      std::make_pair("USE_DPORT", "FALSE"), std::make_pair("USE_MULT", "MULTIPLY"),
                      std::make_pair("USE_SIMD", "ONE48")}) {
        auto it = c->params.find(a->id(pair.first));
        if (it == c->params.end() || it->second.as_string() != pair.second) return false;
    }
    auto inv = c->params.find(a->id("IS_CLK_INVERTED"));
    if (inv != c->params.end() && inv->second.as_bool()) return false;
    auto pat = c->params.find(a->id("USE_PATTERN_DETECT"));
    if (pat != c->params.end() && pat->second.as_string() != "NO_PATDET") return false;
    for (int i = 0; i < 7; ++i)
        if (preg_constant_pin(a, c, "OPMODE" + std::to_string(i)) != ((0x35 >> i) & 1)) return false;
    for (auto group : {std::make_pair("ALUMODE", 4), std::make_pair("INMODE", 5), std::make_pair("CARRYINSEL", 3)})
        for (int i = 0; i < group.second; ++i)
            if (preg_constant_pin(a, c, std::string(group.first) + std::to_string(i)) != 0) return false;
    if (preg_constant_pin(a, c, "CARRYIN") != 0) return false;
    auto clk = get_net_or_empty(c, a->id("CLK"));
    if (!clk || !clk->driver.cell || clk->driver.cell->type == id_PSEUDO_GND || clk->driver.cell->type == id_PSEUDO_VCC)
        return false;
    for (const auto &p : c->ports) {
        if (!p.second.net) continue;
        auto base = preg_pin_base(a, p.first);
        if (p.second.type == PORT_OUT) {
            if (base != "P") return false; // Cascaded/pattern outputs outside this profile.
        } else if (base != "A" && base != "B" && base != "C" && base != "CLK" && base != "CEP" && base != "RSTP") {
            if (preg_constant_pin(a, c, p.first.str(a)) < 0) return false;
        }
    }
    return true;
}

static double preg_setup_ns(const std::string &base)
{
    if (base == "A" || base == "B") return 5.89;
    if (base == "C") return 2.11;
    if (base == "CEP") return 0.54;
    if (base == "RSTP") return 0.37;
    return 0.0;
}
