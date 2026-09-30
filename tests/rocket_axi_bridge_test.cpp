#include "Vaxi64_to_wb32.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
struct Sim {
 Vaxi64_to_wb32 d;std::array<uint32_t,256> memory{};
 unsigned reads=0,writes=0,cycles=0,delay=0;bool pending=false;uint32_t addr=0,data=0;unsigned sel=0;bool we=false;
 Sim(){d.rst=1;for(unsigned i=0;i<5;i++)tick();d.rst=0;tick();}
 void tick(){
  if(++cycles>100000)throw std::runtime_error("timeout");
  d.clk=0;d.wb_ack=0;d.wb_err=0;d.eval();
  if(d.rst){pending=false;delay=0;}
  if(pending){
   check(d.wb_cyc&&d.wb_stb&&d.wb_adr==addr&&bool(d.wb_we)==we&&d.wb_sel==sel&&(!we||d.wb_dat_w==data),"WB request changed while stalled");
   if(delay)delay--;
   else {
    d.wb_err=addr>=memory.size();d.wb_ack=!d.wb_err;
    d.wb_dat_r=d.wb_err?0:memory[addr];
    if(!d.wb_err){if(we){for(unsigned b=0;b<4;b++)if(sel&(1<<b))memory[addr]=(memory[addr]&~(255U<<(b*8)))|(data&(255U<<(b*8)));writes++;}else reads++;}
   }
  } else if(d.wb_cyc&&d.wb_stb){pending=true;addr=d.wb_adr;we=d.wb_we;sel=d.wb_sel;data=d.wb_dat_w;delay=(cycles*7)%5;}
  d.eval();bool completed=pending&&(d.wb_ack||d.wb_err);
  d.clk=1;d.eval();if(completed)pending=false;
  d.clk=0;d.wb_ack=0;d.wb_err=0;d.eval();
 }
 void aw(uint32_t a,unsigned size,unsigned n=1,unsigned burst=1){d.aw_valid=1;d.aw_addr=a;d.aw_size=size;d.aw_len=n-1;d.aw_burst=burst;d.aw_id=9;d.eval();while(!d.aw_ready)tick();tick();d.aw_valid=0;d.eval();}
 void w(uint64_t value,unsigned mask,bool last=true){d.w_valid=1;d.w_data=value;d.w_strb=mask;d.w_last=last;d.eval();while(!d.w_ready)tick();tick();d.w_valid=0;d.eval();}
 void b(unsigned response=0){while(!d.b_valid)tick();for(int i=0;i<7;i++){check(d.b_valid&&d.b_id==9&&d.b_resp==response,"B response");tick();}d.b_ready=1;tick();d.b_ready=0;}
 std::vector<uint64_t> read(uint32_t a,unsigned size,unsigned n=1,unsigned burst=1,unsigned response=0){
  d.ar_valid=1;d.ar_addr=a;d.ar_size=size;d.ar_len=n-1;d.ar_burst=burst;d.ar_id=6;d.eval();while(!d.ar_ready)tick();tick();d.ar_valid=0;d.eval();
  std::vector<uint64_t> result;
  for(unsigned j=0;j<n;j++){
   while(!d.r_valid)tick();uint64_t v=d.r_data;
   for(int i=0;i<7;i++){check(d.r_valid&&d.r_id==6&&d.r_resp==response&&bool(d.r_last)==(j+1==n)&&d.r_data==v,"R response hold");tick();}
   result.push_back(v);d.r_ready=1;tick();d.r_ready=0;
  }
  return result;
 }
};
int main(){try{
 Sim s;
 // Write data preceding its independently stalled address.
 s.w(0x1122334455667788ULL,255);for(int i=0;i<8;i++)s.tick();s.aw(0,3);s.b();
 check(s.read(0,3)[0]==0x1122334455667788ULL,"64-bit transfer");
 for(unsigned size=0;size<=2;size++)for(unsigned byte=0;byte<8;byte+=(1<<size)){
  uint64_t v=0xaabbccddc0decafeULL;unsigned mask=((1U<<(1<<size))-1)<<byte;
  s.aw(32+byte,size);s.w(v,mask);s.b();
  unsigned before=s.reads;auto r=s.read(32+byte,size)[0];
  check(s.reads==before+1,"narrow read touched adjacent MMIO register");
  unsigned shift=(byte&4)*8;check(uint32_t(r>>shift)==s.memory[(32+byte)/4],"narrow lane placement");
 }
 s.aw(128,3,8);for(unsigned i=0;i<8;i++)s.w(0xfeed000000000000ULL+i,255,i==7);s.b();
 auto burst=s.read(128,3,8);for(unsigned i=0;i<8;i++)check(burst[i]==0xfeed000000000000ULL+i,"cache line burst");
 s.aw(256,2,4,0);for(unsigned i=0;i<4;i++)s.w(i+1,15,i==3);s.b();
 auto fixed=s.read(256,2,4,0);for(auto v:fixed)check(v==4,"fixed address burst");
 unsigned before=s.writes;s.aw(0,3);s.w(0,0);s.b();check(before==s.writes,"zero strobes wrote memory");
 before=s.writes;s.aw(0,2);s.w(0,240);s.b(2);check(before==s.writes,"invalid strobes wrote memory");
 before=s.reads;s.read(1,2,1,1,2);s.read(0,4,1,1,2);s.read(0,2,1,2,2);check(before==s.reads,"invalid read touched memory");
 s.read(4096,3,2,1,2);s.aw(4096,3);s.w(0,255);s.b(2);
 // Reset cancels a buffered W beat; it must not leak into the next write.
 s.w(0xbad,255);s.d.rst=1;s.tick();s.d.rst=0;s.tick();s.aw(8,3);s.w(42,255);s.b();check(s.read(8,3)[0]==42,"reset buffer");
 std::cout<<"PASS: burst/narrow AXI, AW/W ordering, backpressure, errors, reset; "<<s.cycles<<" cycles\n";
 return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
