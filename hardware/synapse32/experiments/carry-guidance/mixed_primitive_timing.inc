// Optional DS182 diagnostic guidance. This does not validate the remaining
// routing, LUT, carry, skew, hold, reset or DDR IO timing models.
namespace {
struct TinyPrimitiveTiming {
    TimingPortClass cls = TMG_IGNORE;
    const char *clock = "CLK";
    double setup = 0, hold = 0, cq = 0;
    bool clocked = false;
};
static int tinyParam(const Arch *ctx, const CellInfo *c, const std::string &name)
{
    auto it = c->params.find(ctx->id(name));
    return it == c->params.end() ? 0 : int(it->second.as_int64());
}
static std::string tinyAttr(const Arch *ctx, const CellInfo *c, const std::string &name)
{
    auto it = c->attrs.find(ctx->id(name));
    return it == c->attrs.end() ? "" : it->second.as_string();
}
static int tinyConstant(const Arch *ctx, const CellInfo *c, IdString port)
{
    auto it = c->ports.find(port);
    int value = -1;
    if (it != c->ports.end() && it->second.net && it->second.net->driver.cell) {
        IdString t = it->second.net->driver.cell->type;
        if (t == ctx->id("PSEUDO_GND")) value = 0;
        if (t == ctx->id("PSEUDO_VCC")) value = 1;
    }
    std::string pin = port.str(ctx);
    for (int k = 0; k < 2 && value < 0; ++k) {
        std::string names = " " + tinyAttr(ctx,c,k ? "DSP_VCC_PINS" : "DSP_GND_PINS") + " ";
        if (names.find(" " + pin + " ") != std::string::npos) value = k;
    }
    if (value < 0) return -1;
    std::string orig = tinyAttr(ctx,c,"X_ORIG_PORT_" + pin);
    if (orig.empty()) {
        orig = pin;
        size_t n = orig.find_first_of("0123456789");
        if (n != std::string::npos) orig = pin.substr(0,n) + "[" + pin.substr(n) + "]";
    }
    return value ^ tinyParam(ctx,c,"IS_" + orig + "_INVERTED");
}
static int tinyWord(const Arch *ctx, const CellInfo *c, const char *base, int width)
{
    int result = 0;
    for (int i = 0; i < width; ++i) {
        int v = tinyConstant(ctx,c,ctx->id(std::string(base) + std::to_string(i)));
        NPNR_ASSERT_MSG(v >= 0,"Primitive guidance requires constant DSP mode pins");
        result |= v << i;
    }
    return result;
}
static bool tinyPrimitiveTiming(const Arch *ctx, const CellInfo *c, IdString port, TinyPrimitiveTiming &t)
{
    if (std::getenv("TINY3TPU_PRIMITIVE_GUIDANCE") == nullptr) return false;
    const std::string pin = port.str(ctx);
    auto input = [&](const char *clock, double setup, double hold) {
        t.cls=TMG_REGISTER_INPUT; t.clock=clock; t.setup=setup; t.hold=hold; t.clocked=true;
    };
    auto output = [&](const char *clock, double cq) {
        auto it=c->ports.find(port);
        if(it!=c->ports.end() && it->second.net && !it->second.net->users.empty()) {
            t.cls=TMG_REGISTER_OUTPUT; t.clock=clock; t.cq=cq; t.clocked=true;
        }
    };
    if (c->type == ctx->id("SLICE_LUTX")) {
        auto attr=c->attrs.find(ctx->id("X_LUT_AS_DRAM"));
        if(attr==c->attrs.end() || !attr->second.as_bool()) return false;
        NPNR_ASSERT(tinyAttr(ctx,c,"X_ORIG_TYPE")=="RAMD32");
        NPNR_ASSERT(tinyParam(ctx,c,"IS_WCLK_INVERTED")==0);
        bool observable=false;
        for(auto &p:c->ports) if(p.second.type==PORT_OUT && p.second.net && !p.second.net->users.empty()) {
            NPNR_ASSERT(tinyAttr(ctx,c,"X_ORIG_PORT_"+p.first.str(ctx))=="O");
            observable=true;
        }
        if(!observable) return false;
        std::string orig=tinyAttr(ctx,c,"X_ORIG_PORT_"+pin);
        if(orig=="CLK") t.cls=TMG_CLOCK_INPUT;
        else if(orig=="O") {
            t.cls=TMG_COMB_OUTPUT; t.clock="CLK"; t.cq=1.44; t.clocked=true;
        }
        else if(orig=="I") input("CLK",.69,.33);
        else if(orig=="WE") input("CLK",.46,.11);
        else if(orig.size()==5 && orig.substr(0,4)=="WADR" && orig[4]>='0' && orig[4]<='4') input("CLK",.63,.63);
        else if(orig.size()==5 && orig.substr(0,4)=="RADR" && orig[4]>='0' && orig[4]<='4') t.cls=TMG_COMB_INPUT;
        else {
            NPNR_ASSERT(orig.empty() && pin.size()==2 && pin[0]=='A' && pin[1]>='1' && pin[1]<='6');
            return false; // Retain native class on shared unused read inputs.
        }
        return true;
    }
    if (c->type == ctx->id("RAMB36E1_RAMB36E1")) {
        NPNR_ASSERT(tinyParam(ctx,c,"READ_WIDTH_A")==2 && tinyParam(ctx,c,"WRITE_WIDTH_A")==2);
        NPNR_ASSERT(tinyParam(ctx,c,"READ_WIDTH_B")==0 && tinyParam(ctx,c,"WRITE_WIDTH_B")==0);
        NPNR_ASSERT(tinyParam(ctx,c,"DOA_REG")==0 && tinyParam(ctx,c,"DOB_REG")==0);
        NPNR_ASSERT(tinyParam(ctx,c,"IS_CLKARDCLK_INVERTED")==0);
        std::string orig=tinyAttr(ctx,c,"X_ORIG_PORT_"+pin);
        std::string base=orig.substr(0,orig.find('['));
        if(base=="CLKARDCLK") t.cls=TMG_CLOCK_INPUT;
        else if(base=="DOADO") output("CLKARDCLKL",2.44);
        else if(base=="ADDRARDADDR") input("CLKARDCLKL",.65,.38);
        else if(base=="DIADI" || base=="DIPADIP") input("CLKARDCLKL",.78,.64);
        else if(base=="ENARDEN") input("CLKARDCLKL",.48,.32);
        else if(base=="WEA") input("CLKARDCLKL",.54,.29);
        else if(base=="RSTRAMARSTRAM") input("CLKARDCLKL",.34,.40);
        return true;
    }
    if (c->type != ctx->id("DSP48E1_DSP48E1")) return false;
    const char *regs[]={"AREG","BREG","CREG","DREG","ADREG","MREG","PREG","ACASCREG","BCASCREG",
                        "ALUMODEREG","CARRYINREG","CARRYINSELREG","INMODEREG","OPMODEREG"};
    bool registered=false;
    for(auto r:regs) registered |= tinyParam(ctx,c,r)!=0;
    if(!registered) return false; // Existing combinational DSP model is retained.
    // Narrow profile deliberately excludes hybrid registered/bypass outputs.
    // The blocked carry-save multiplier has only MREG output origins.
    NPNR_ASSERT_MSG(tinyWord(ctx,c,"OPMODE",7)==5,"Primitive guidance requires pure registered multiply DSPs");
    NPNR_ASSERT(tinyWord(ctx,c,"INMODE",5)==0 && tinyWord(ctx,c,"ALUMODE",4)==0);
    NPNR_ASSERT(tinyWord(ctx,c,"CARRYINSEL",3)==0 && tinyConstant(ctx,c,ctx->id("CARRYIN"))==0);
    NPNR_ASSERT(tinyParam(ctx,c,"MREG")==1 && tinyParam(ctx,c,"PREG")==0);
    int a=tinyParam(ctx,c,"AREG"), b=tinyParam(ctx,c,"BREG");
    NPNR_ASSERT(a<=1 && b<=1 && tinyParam(ctx,c,"ACASCREG")==a && tinyParam(ctx,c,"BCASCREG")==b);
    for(auto r:regs) {
        std::string s=r;
        if(s!="AREG" && s!="BREG" && s!="ACASCREG" && s!="BCASCREG" && s!="MREG") NPNR_ASSERT(tinyParam(ctx,c,r)==0);
    }
    NPNR_ASSERT(tinyParam(ctx,c,"IS_CLK_INVERTED")==0);
    std::string base=pin.substr(0,pin.find_first_of("0123456789"));
    if(pin=="CLK") t.cls=TMG_CLOCK_INPUT;
    else if(base=="P") output("CLK",2.31);
    else if(base=="A") input("CLK",a ? .38 : 3.66,a ? .18 : 0);
    else if(base=="B") input("CLK",b ? .51 : 3.66,b ? .18 : 0);
    else if((pin=="RSTA" && a) || (pin=="RSTB" && b)) input("CLK",.53,.34);
    else if((pin=="CEA2" && a) || (pin=="CEB2" && b)) input("CLK",.55,.09);
    else if(pin=="RSTM") input("CLK",.24,.29);
    else if(pin=="CEM") input("CLK",.39,.25);
    else {
        auto it=c->ports.find(port);
        if(it!=c->ports.end() && it->second.type==PORT_OUT) {
            NPNR_ASSERT_MSG(!it->second.net || it->second.net->users.empty(),"Unmodeled live DSP output");
        } else NPNR_ASSERT_MSG(tinyConstant(ctx,c,port)>=0,"Unmodeled live registered DSP input");
    }
    return true;
}
} // namespace
