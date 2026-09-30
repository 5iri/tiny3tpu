        // Optimization guidance only: this is not validated Kintex timing.
        // Disabled by default, leaving the original missing-arc behavior exact.
        static const int guidance_ps = []() {
            const char *value = std::getenv("TINY3TPU_CARRY_GUIDANCE_PS");
            if (value == nullptr)
                return -1;
            char *end = nullptr;
            long parsed = std::strtol(value, &end, 10);
            if (*value == '\0' || *end != '\0' || parsed < 0 || parsed > 1000)
                log_error("TINY3TPU_CARRY_GUIDANCE_PS must be an integer in 0..1000.\n");
            log_warning("CARRY4 optimization guidance enabled: %ld ps symbolic arcs; not validated device timing.\n", parsed);
            return int(parsed);
        }();
        if (guidance_ps >= 0) {
            const IdString s_pins[] = {id_S0, id_S1, id_S2, id_S3};
            const IdString d_pins[] = {id_DI0, id_DI1, id_DI2, id_DI3};
            const IdString o_pins[] = {id_O0, id_O1, id_O2, id_O3};
            const IdString co_pins[] = {id_CO0, id_CO1, id_CO2, id_CO3};
            std::array<int, 9> values;
            auto constant = [&](IdString pin) {
                const auto *net = get_net_or_empty(cell, pin);
                if (net != nullptr && net->driver.cell != nullptr) {
                    if (net->driver.cell->type == id_PSEUDO_GND) return 0;
                    if (net->driver.cell->type == id_PSEUDO_VCC) return 1;
                }
                return -1;
            };
            int input = -1, output = -1;
            for (int i = 0; i < 4; ++i) {
                values[i] = constant(s_pins[i]);
                values[i + 4] = constant(d_pins[i]);
                if (fromPort == s_pins[i]) input = i;
                if (fromPort == d_pins[i]) input = i + 4;
                if (toPort == o_pins[i]) output = 2 * i;
                if (toPort == co_pins[i]) output = 2 * i + 1;
            }
            int initial = int_or_default(cell->params, id("PRECYINIT_CONST"), -1);
            if (initial >= 0) {
                NPNR_ASSERT(initial <= 1);
                values[8] = initial;
            } else {
                IdString initial_pin = cell->ports.count(id_CIN) ? id_CIN : id_CYINIT;
                values[8] = cell->ports.count(initial_pin) ? constant(initial_pin) : 0;
                if (fromPort == initial_pin) input = 8;
            }
            if (input >= 0 && output >= 0 &&
                (tiny3tpu::carry_support(values)[output] & (1u << input))) {
                delay = getDelayFromNS(guidance_ps / 1000.0);
                return true;
            }
        }
