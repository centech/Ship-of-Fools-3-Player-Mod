#!/usr/bin/env python3
"""Execute the installed x64 payload under Unicorn with simulated game objects.

This exercises compiled code and real hook trampolines; engine calls are stubs.
It does not replace a live three-controller gameplay test.
"""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import subprocess
import ctypes as C
import unicorn as U
from unicorn import x86_const as X
import pefile

ROOT = Path(__file__).resolve().parent
GAME_DLL = Path(os.environ.get('SOF_TEST_DLL', 'GameAssembly.dll'))
HAS_GAME_DLL = GAME_DLL.is_file()
GAME_DLL_REASON = 'Set SOF_TEST_DLL to your verified original game DLL for this test.'
spec = importlib.util.spec_from_file_location('patch',ROOT.parent/'patch_third_player.py')
patch = importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
MANIFEST = json.loads((ROOT/'manifest.json').read_text())

# Field order follows the game's generated il2cpp.h. Nullable<T> stores VALUE
# FIRST and has_value LAST in this build. Verify this against native get_Value
# below, independently of the mod's own code.
class NullableU64(C.Structure):
    _fields_=[('value',C.c_uint64),('has_value',C.c_bool)]
class Information(C.Structure):
    _fields_=[('achievements',C.c_uint64),('client',NullableU64),
              ('dlcs',C.c_int32),('name',C.c_ubyte*128),('number',C.c_int32)]
class NullableInformation(C.Structure):
    _fields_=[('value',Information),('has_value',C.c_bool)]
class NullableInt(C.Structure):
    _fields_=[('value',C.c_int32),('has_value',C.c_bool)]
class Blueprint(C.Structure):
    _fields_=[('character',C.c_int32),('information',NullableInformation),
              ('preselected',NullableInt),('ready',C.c_bool)]

class Game:
    def __init__(self, base=0x180000000, controllers=(4,5), players=2):
        self.base=base;self.controllers=list(controllers);self.players=players
        self.u=U.Uc(U.UC_ARCH_X86,U.UC_MODE_64)
        self.u.mem_map(base,0x3b00000)
        self.u.mem_write(base+MANIFEST['code_rva'],(ROOT/'code.bin').read_bytes())
        self.u.mem_write(base+MANIFEST['data_rva'],(ROOT/'state.bin').read_bytes())
        self.heap=0x500000000;self.u.mem_map(self.heap,0x200000)
        self.stack=0x700000000;self.u.mem_map(self.stack,0x200000)
        self.next=self.heap;self.stop=base+0x100
        self.handles={};self.next_handle=1;self.actors=[];self.spawn_calls=[]
        self.dispatch_calls=[];self.original_calls=[];self.logs=[];self.input_calls=[]
        self.scene=self.obj(0x200);self.ps=self.obj(0x100);self.input=self.obj(0x40)
        self.ptr(self.scene+0xa0,self.ps)
        for off in [0x78,0x1e,0x22]:self.write(self.scene+off,b'\1')
        self.actor1=self.obj(0x200);self.actor2=self.obj(0x200)
        self.i32(self.actor1+0x148,controllers[0]);self.i32(self.actor2+0x148,controllers[1])
        self.actors=[self.actor1,self.actor2]
        self.blueprints=self.obj(0x20+2*0xc0);self.i32(self.blueprints+0x18,players)
        for i in range(2):
            bp=self.blueprints+0x20+i*0xc0
            value=Blueprint();value.character=10+i
            value.information.has_value=True;value.information.value.number=i
            self.write(bp,bytes(value))
        self.callbacks={
            0x6dde75:lambda:self.original('spawn',5),
            0x925a26:lambda:self.original('reset',6),
            0x6dd436:lambda:self.original('despawn',6),
            0x1187036:lambda:self.original('input_awake',6),
            0x8c0e95:self.inventory_update,
            0x8c0499:self.inventory_match,
            0x8bf670:self.inventory_link,0x8c03a0:self.inventory_toggle,
            0x5026e0:lambda:self.ret(len(self.actors)),
            0x119c810:lambda:self.ret(self.actors[self.r('rdx')]),
            0x923330:self.get_controller,0xad0880:self.is_keyboard,
            0x9228f0:self.assigned,0x6ddba0:self.spawn,
            0x318cf0:self.new_handle,0x318ce0:self.target,0x318cd0:self.free,
            0x319600:self.string,0xd9b9b0:self.log,0x6dc7f0:self.dispatch,
            0x1d36a20:self.clone_editor,0xce5da0:self.new_id,
            0x495c60:lambda:self.name(0x18),0x495c50:lambda:self.name(0x20),
            0x397c60:self.metadata,0x23ca7e0:self.add_editor,
        }
        for address in self.callbacks:self.write(base+address,b'\xc3')
        self.u.hook_add(U.UC_HOOK_CODE,self.code)
        self.native_call_count=0
        self.unwind_checks=0

    def write(self,address,data):self.u.mem_write(address,data)
    def read(self,address,n):return bytes(self.u.mem_read(address,n))
    def obj(self,size):
        p=self.next;self.next+=(size+15)//16*16;return p
    def ptr(self,p,v=None):
        if v is None:return struct.unpack('<Q',self.read(p,8))[0]
        self.write(p,struct.pack('<Q',v))
    def i32(self,p,v=None):
        if v is None:return struct.unpack('<i',self.read(p,4))[0]
        self.write(p,struct.pack('<i',v))
    def r(self,reg):return self.u.reg_read(getattr(X,'UC_X86_REG_'+reg.upper()))
    def setr(self,reg,value):self.u.reg_write(getattr(X,'UC_X86_REG_'+reg.upper()),value)
    def ret(self,value=0):
        sp=self.r('rsp');rip=self.ptr(sp)
        # Simulate ordinary native callees clobbering every volatile register.
        for reg in ['rcx','rdx','r8','r9','r10','r11']:self.setr(reg,0xaabbaabb)
        self.setr('rax',value);self.setr('rsp',sp+8);self.setr('rip',rip)
    def args(self):return [self.r(x) for x in ['rcx','rdx','r8','r9']]
    def code(self,uc,address,size,data):
        if address==self.stop:self.u.emu_stop();return
        callback=self.callbacks.get(address-self.base)
        if callback:
            # Windows x64: at function entry return address leaves RSP == 8 mod16.
            if (address-self.base) not in [0x6dde75,0x925a26,0x6dd436,0x1187036,0x8c0e95,0x8c0499,0x6c6189,0x6c6199,0x6c575a,0x8c0f4e]:
                assert self.r('rsp')%16==8,hex(address)
                if not getattr(self,'native_integration',False):self.check_unwind()
            self.native_call_count+=1
            callback()
    def call(self,name,*args):
        sp=self.stack+0x1ff008;self.setr('rsp',sp);self.ptr(sp,self.stop)
        saved={reg:0x112233440000+i for i,reg in enumerate(['rbx','rbp','rsi','rdi','r12','r13','r14','r15'])}
        self.saved=saved;self.top_sp=sp
        for reg,v in saved.items():self.setr(reg,v)
        for reg,v in zip(['rcx','rdx','r8','r9'],args):self.setr(reg,v)
        rva=name if isinstance(name,int) else MANIFEST['symbols'][name]['rva']
        self.u.emu_start(self.base+rva,self.stop+1,count=50000)
        assert self.r('rip')==self.stop,name
        assert self.r('rsp')==sp+8,name
        for reg,v in saved.items():assert self.r(reg)==v,(name,reg,hex(self.r(reg)),hex(v))
    def check_unwind(self):
        # Use precisely the generated Windows unwind operations to recover the
        # entire chain of live helper frames at each simulated engine call.
        registers=dict((r,self.r(r)) for r in self.saved)
        register_names=['rax','rcx','rdx','rbx','rsp','rbp','rsi','rdi']+[f'r{i}' for i in range(8,16)]
        sp=self.r('rsp')+8;pc=self.ptr(self.r('rsp'))
        while pc!=self.stop:
            f=next((f for f in MANIFEST['functions'] if f['begin']<=pc-self.base<f['end']),None)
            assert f is not None,hex(pc)
            info=bytes.fromhex(f['unwind']);i=0
            assert pc-self.base-f['begin']>=info[1]
            while i<info[2]:
                op=info[5+i*2]&15;extra=info[5+i*2]>>4;i+=1
                if op==0:
                    registers[register_names[extra]]=self.ptr(sp);sp+=8
                elif op==2:sp+=extra*8+8
                elif op in [1,4]:
                    amount=struct.unpack_from('<H',info,4+i*2)[0]*8;i+=1
                    if op==1:sp+=amount
                    else:registers[register_names[extra]]=self.ptr(sp+amount)
                else:raise AssertionError(op)
            pc=self.ptr(sp);sp+=8
        assert sp==self.top_sp+8,(hex(sp),hex(self.top_sp+8))
        assert registers==self.saved,(registers,self.saved)
        self.unwind_checks+=1
    def original(self,which,stolen):
        self.original_calls.append(which)
        # Trampolines have executed the original prologue instructions. Simulate
        # the original function body/epilogue using the actual saved stack slots.
        if which=='spawn':self.setr('rbx',self.ptr(self.r('rsp')+8))
        elif which=='reset':
            for reg in ['r14','r13','rsi']:
                sp=self.r('rsp');self.setr(reg,self.ptr(sp));self.setr('rsp',sp+8)
        else:
            self.setr('rsp',self.r('rsp')+0x20)
            reg='rbx' if which=='input_awake' else 'rsi'
            sp=self.r('rsp');self.setr(reg,self.ptr(sp));self.setr('rsp',sp+8)
        self.ret()
    def get_controller(self):
        ps,index,_,_=self.args();assert ps==self.ps
        self.ret(self.controllers[index]&0xffffffff)
    def is_keyboard(self):self.ret(self.r('rcx')==1)
    def assigned(self):assert self.r('rcx')==self.ps;self.ret(self.blueprints)
    def spawn(self):
        scene,bp,_,_=self.args();assert scene==self.scene
        data=self.read(bp,0xc0);self.spawn_calls.append(data)
        actor=self.obj(0x200);self.write(actor+0x1d,b'\1');self.i32(actor+0x148,self.controllers[1])
        self.actors.append(actor);self.ret(actor)
    def new_handle(self):
        actor,pinned,*_=self.args();assert pinned==0
        h=self.next_handle;self.next_handle+=1;self.handles[h]=actor;self.ret(h)
    def target(self):self.ret(self.handles.get(self.r('rcx'),0))
    def free(self):del self.handles[self.r('rcx')];self.ret()
    def string(self):
        p=self.r('rcx');s=bytearray()
        while self.read(p,1)!=b'\0':s.extend(self.read(p,1));p+=1
        self.logs.append(s.decode());self.ret(self.obj(0x40))
    def log(self):self.ret()
    def dispatch(self):
        scene,controller,inp,_=self.args();self.dispatch_calls.append((controller,inp))
        # This models FirstOrDefault's real predicate: actor.Controller == id.
        for actor in self.actors:
            if self.i32(actor+0x148)==controller:
                self.ptr(actor+0x168,inp);break
        self.ret()
    def clone_editor(self):
        p=self.obj(0x70);self.write(p,self.read(self.r('rcx'),0x70));self.ret(p)
    def new_id(self):
        user=self.r('rcx');id=self.i32(user+0x118);self.i32(user+0x118,id+1);self.ret(id)
    def name(self,off):p,s,*_=self.args();self.ptr(p+off,s);self.ret()
    def metadata(self):self.ptr(self.r('rcx'),self.heap+0x1f0000);self.ret()
    def add_editor(self):
        list,p,method,_=self.args();assert method==self.heap+0x1f0000
        n=self.i32(list+0x18);items=self.ptr(list+0x10)
        self.ptr(items+0x20+n*8,p);self.i32(list+0x18,n+1);self.ret()
    def inventory_toggle(self):
        inv=self.r('rcx');actor=self.ptr(inv+0xc0)
        active=not self.read(inv+0x90,1)[0]
        self.write(inv+0x90,bytes([active]));self.write(actor+0x111,bytes([active]))
        self.ret()
    def inventory_link(self):
        inv=self.r('rcx');owner=self.state(48)
        old=self.ptr(inv+0xc0)
        assert self.read(old+0x111,1)==b'\0', 'Old actor must leave inventory before rebind'
        self.ptr(inv+0xc0,self.handles[self.state(8)] if owner==3 else self.actor2)
        self.ret()
    def inventory_update(self):
        inv=self.r('rcx');actor=self.ptr(inv+0xc0);inp=self.ptr(actor+0x168)
        if inp and self.read(inp+0x2d,1)==b'\1':
            active=not self.read(inv+0x90,1)[0]
            self.write(inv+0x90,bytes([active]));self.write(actor+0x111,bytes([active]))
        # Trampoline saved RBX in caller shadow space; restore it as native Update does.
        self.setr('rbx',self.ptr(self.r('rsp')+0x10));self.ret()
    def inventory_match(self):
        inv,actor,*_=self.args()
        number=0 if actor==self.actor1 else 1
        result=number==self.i32(inv+0x20)
        self.setr('rsp',self.r('rsp')+0x160)
        sp=self.r('rsp');self.setr('rbx',self.ptr(sp));self.setr('rsp',sp+8)
        self.ret(result)
    def inventory_fixture(self):
        self.start();self.press(7)
        inv=self.obj(0x100);self.i32(inv+0x20,1);self.ptr(inv+0xc0,self.actor2)
        self.ptr(inv+0xc8,self.obj(0x30))
        for actor in self.actors:self.ptr(actor+0x168,self.obj(0x40))
        return inv
    def inventory_button(self,actor,on):
        self.write(self.ptr(actor+0x168)+0x2d,bytes([on]))
    def start(self):self.call('third_spawn',self.scene,0)
    def press(self,id,down=True):
        self.write(self.input+0x32,bytes([down]));self.call('third_dispatch',self.scene,id,self.input,0)
    def state(self,off):return self.i32(self.base+MANIFEST['data_rva']+off)

class PayloadTests(unittest.TestCase):
    def test_only_unused_gamepad_joins(self):
        g=Game();g.start()
        for id in [4,5,1,0,0xffffffff]:g.press(id)
        g.press(7,False);self.assertEqual(len(g.spawn_calls),0)
        g.press(7);self.assertEqual(len(g.spawn_calls),1)
        self.assertEqual(g.state(12),7)
        self.assertEqual(struct.unpack_from('<i',g.spawn_calls[0],0)[0],11)
        self.assertEqual(Blueprint.from_buffer_copy(g.spawn_calls[0]).information.value.number,1)
        self.assertEqual(g.spawn_calls[0][0xb8],1)
        for _ in range(4):g.press(7)
        self.assertEqual(len(g.spawn_calls),1)
    def test_independent_inputs_and_ownership_reassignment(self):
        g=Game();g.start();g.press(7);clone=g.actors[-1]
        inputs=[g.obj(0x40) for _ in range(3)]
        # Netcode may initialize clone ownership after SpawnPlayer returns.
        g.i32(clone+0x148,5)
        for id,inp in zip([4,5,7],inputs):g.call('third_dispatch',g.scene,id,inp,0)
        self.assertEqual([g.ptr(p+0x168) for p in g.actors],inputs)
        self.assertEqual([g.i32(p+0x148) for p in g.actors],[4,5,7])
    def test_keyboard_and_two_pads(self):
        g=Game(controllers=(1,4));g.start();g.press(5)
        self.assertEqual(len(g.spawn_calls),1);self.assertEqual(g.state(12),5)
    def test_reversed_blueprints(self):
        g=Game();p=g.blueprints+0x20
        a,b=g.read(p,0xc0),g.read(p+0xc0,0xc0)
        g.write(p,b);g.write(p+0xc0,a);g.start();g.press(7)
        self.assertEqual(struct.unpack_from('<i',g.spawn_calls[0])[0],11)
    @unittest.skipUnless(HAS_GAME_DLL, GAME_DLL_REASON)
    def test_native_game_nullable_layout(self):
        import os
        self.assertEqual(C.sizeof(Information),0xa0)
        self.assertEqual(C.sizeof(Blueprint),0xc0)
        self.assertEqual(Blueprint.information.offset,8)
        self.assertEqual(NullableInformation.has_value.offset,0xa0)
        self.assertEqual(Information.number.offset,0x9c)
        # Execute the game's original Nullable<PlayerInformation>.get_Value,
        # not a stub. It must read the same bytes our fixture and mod inspect.
        baseline=Path(os.environ.get('SOF_TEST_DLL','GameAssembly.dll')).read_bytes()
        p=pefile.PE(data=baseline,fast_load=True)
        g=Game();address=0x8df680
        g.write(g.base+address,p.get_data(address,0x6f))
        out=g.obj(0xa0);bp=g.blueprints+0x20+0xc0
        g.call(address,out,bp+Blueprint.information.offset,0)
        info=Information.from_buffer_copy(g.read(out,0xa0))
        self.assertEqual(info.number,1)
        self.assertEqual(info.achievements,0)
        g.start();g.press(7)
        self.assertEqual(len(g.spawn_calls),1)
    def test_achievements_do_not_determine_presence(self):
        for achievements in [0,1,0xffffffffffffffff]:
            g=Game();bp=g.blueprints+0x20+0xc0
            value=Blueprint.from_buffer_copy(g.read(bp,0xc0))
            value.information.value.achievements=achievements
            g.write(bp,bytes(value));g.start();g.press(7)
            self.assertEqual(len(g.spawn_calls),1)
    def test_missing_information_rejected_despite_poisoned_padding(self):
        g=Game();bp=g.blueprints+0x20+0xc0
        value=Blueprint.from_buffer_copy(g.read(bp,0xc0))
        value.information.has_value=False
        value.information.value.achievements=1
        g.write(bp,bytes(value));g.i32(bp+0xac,1)
        g.start();g.press(7)
        self.assertEqual(len(g.spawn_calls),0)
    def test_controller_diagnostics_are_bounded(self):
        g=Game();g.start()
        for _ in range(20):g.press(7)
        messages=[line for line in g.logs if 'Gameplay button' in line]
        self.assertEqual(messages,['[ThirdPlayer] Gameplay button from controller 07.'])
    def test_single_player_and_remote_sessions(self):
        for kind in ['single','remote','client','menu']:
            g=Game(players=1 if kind=='single' else 2)
            if kind=='remote':g.write(g.ps+0xe1,b'\1')
            if kind=='client':g.write(g.scene+0x1e,b'\0')
            if kind=='menu':g.write(g.scene+0x78,b'\0')
            g.start();g.press(7);self.assertEqual(len(g.spawn_calls),0,kind)
            self.assertEqual(len(g.dispatch_calls),1)
    def test_scene_transition_and_reset(self):
        g=Game();g.start();g.press(7)
        g.call('third_despawn',g.scene,0);self.assertFalse(g.handles)
        g.start();self.assertEqual(len(g.spawn_calls),2)
        g.call('third_reset',g.ps,0);self.assertFalse(g.handles)
        g.start();self.assertEqual(len(g.spawn_calls),2);self.assertEqual(g.state(12),-1)
    def test_aslr(self):
        g=Game(base=0x7ffa00000000);g.start();g.press(7)
        self.assertEqual(len(g.spawn_calls),1)
    def test_shared_inventory_switches_and_clears_old_owner(self):
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1]
        g.inventory_button(clone,True);g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),clone)
        self.assertEqual(g.read(inv+0x90,1),b'\1')
        self.assertEqual(g.read(clone+0x111,1),b'\1')
        self.assertEqual(g.read(g.actor2+0x111,1),b'\0')
        g.inventory_button(clone,False);g.inventory_button(g.actor2,True)
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),g.actor2)
        self.assertEqual(g.read(clone+0x111,1),b'\0')
        self.assertEqual(g.read(g.actor2+0x111,1),b'\1')
        g.inventory_button(g.actor2,False);g.inventory_button(clone,True)
        g.call('third_inventory_update',inv,0)
        # Same owner's next press closes instead of closing then reopening.
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.read(inv+0x90,1),b'\0')
        self.assertEqual(g.read(clone+0x111,1),b'\0')
        g.call('third_reset',g.ps,0);self.assertFalse(g.handles)
    def test_inventory_returns_to_replaced_player_two(self):
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1];old=g.actor2
        g.inventory_button(clone,True);g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),clone)
        g.inventory_button(clone,False)
        replacement=g.obj(0x200);g.ptr(replacement+0x168,g.obj(0x40))
        g.i32(replacement+0x148,g.controllers[1]);g.actor2=replacement
        g.actors=[g.actor1,clone,replacement]
        g.inventory_button(replacement,True)
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),replacement)
        self.assertEqual(g.read(inv+0x90,1),b'\1')
        self.assertEqual(g.read(replacement+0x111,1),b'\1')
        self.assertEqual(g.read(clone+0x111,1),b'\0')
        self.assertNotIn(old,g.handles.values())
        # Repeated character changes while P3 is closed/open must not root old actors.
        for iteration in range(3):
            g.inventory_button(replacement,False);g.inventory_button(clone,True)
            g.call('third_inventory_update',inv,0)
            g.inventory_button(clone,False);g.call('third_inventory_update',inv,0)
            if iteration%2==0:
                g.inventory_button(clone,True);g.call('third_inventory_update',inv,0)
                g.inventory_button(clone,False)
            previous=replacement
            g.actors=[g.actor1,clone]
            g.call('third_inventory_update',inv,0)
            self.assertNotIn(previous,g.handles.values())
            replacement=g.obj(0x200);g.ptr(replacement+0x168,g.obj(0x40))
            g.i32(replacement+0x148,g.controllers[1]);g.actor2=replacement
            g.actors=[g.actor1,clone,replacement]
            g.inventory_button(replacement,True)
            g.call('third_inventory_update',inv,0)
            self.assertEqual(g.ptr(inv+0xc0),replacement)
            self.assertNotIn(previous,g.handles.values())
            self.assertEqual(len(g.handles),2)
        g.call('third_reset',g.ps,0);self.assertFalse(g.handles)
    def test_inventory_simultaneous_buttons_and_player_one(self):
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1]
        g.inventory_button(clone,True);g.inventory_button(g.actor2,True)
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),g.actor2)
        self.assertEqual(g.read(inv+0x90,1),b'\1')
        first=g.obj(0x100);g.ptr(first+0xc0,g.actor1)
        g.inventory_button(g.actor2,False);g.inventory_button(g.actor1,True)
        g.call('third_inventory_update',first,0)
        self.assertEqual(g.ptr(first+0xc0),g.actor1)
        self.assertEqual(g.read(first+0x90,1),b'\1')
        g.i32(inv+0xa8,1);g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),g.actor2)
    def test_inventory_predicate_selects_independent_actor(self):
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1]
        for owner,target in [(2,g.actor2),(3,clone)]:
            g.i32(g.base+MANIFEST['data_rva']+48,owner)
            for actor in g.actors:
                g.call('third_inventory_match',inv,actor,0)
                self.assertEqual(g.r('rax')&255,actor==target)
        g.i32(inv+0x20,0)
        g.call('third_inventory_match',inv,g.actor1,0)
        self.assertEqual(g.r('rax')&255,1)
    @unittest.skipUnless(HAS_GAME_DLL, GAME_DLL_REASON)
    def test_native_inventory_update_consumes_third_button_once(self):
        import os,capstone
        dll=Path(os.environ.get('SOF_TEST_DLL','GameAssembly.dll')).read_bytes()
        pe=pefile.PE(data=dll,fast_load=True)
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1]
        g.native_integration=True
        # Execute real Update through its inventory button and real Toggle,
        # then skip cursor/render work and use Update's original epilogue.
        g.write(g.base+0x8c0e95,pe.get_data(0x8c0e95,0x589))
        g.write(g.base+0x8c03a0,pe.get_data(0x8c03a0,0xe7))
        del g.callbacks[0x8c0e95];del g.callbacks[0x8c03a0]
        movement=g.obj(0x40);shown=g.obj(0x40);hidden=g.obj(0x40)
        audio=g.obj(0x30);g.ptr(audio+0x18,g.obj(0x20));g.ptr(audio+0x20,g.obj(0x20))
        g.ptr(inv+0xb8,movement);g.ptr(inv+0x30,shown);g.ptr(inv+0x28,hidden)
        g.ptr(inv+0x18,audio)
        targets=[]
        def target():targets.append(g.r('rdx'));g.ret()
        g.callbacks.update({0x186ea90:lambda:g.ret(1),
            0x7a6c50:target,0xd96860:lambda:g.ret(inv),0x25de640:lambda:g.ret(),
            0x8c0f4e:lambda:g.setr('rip',g.base+0x8c13fd)})
        md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);md.detail=True
        for ins in md.disasm(pe.get_data(0x8c0e95,0x589),0x8c0e95):
            for op in ins.operands:
                if op.type==capstone.x86.X86_OP_MEM and op.mem.base==capstone.x86.X86_REG_RIP and op.size==8:
                    g.ptr(g.base+ins.address+ins.size+op.mem.disp,g.obj(0x200))
        g.inventory_button(clone,True);g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),clone)
        self.assertEqual(g.read(inv+0x90,1),b'\1')
        self.assertEqual(g.read(clone+0x111,1),b'\1')
        self.assertEqual(targets,[shown])
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.read(inv+0x90,1),b'\0')
        self.assertEqual(g.read(clone+0x111,1),b'\0')
        self.assertEqual(targets,[shown,hidden])
    @unittest.skipUnless(HAS_GAME_DLL, GAME_DLL_REASON)
    def test_native_inventory_rebind_refreshes_actual_actor_trinkets(self):
        import os
        dll=Path(os.environ.get('SOF_TEST_DLL','GameAssembly.dll')).read_bytes()
        pe=pefile.PE(data=dll,fast_load=True)
        g=Game();inv=g.inventory_fixture();clone=g.actors[-1]
        g.native_integration=True
        # Native LinkToPlayer runs its real unsubscribe, bind, portrait and
        # trinket-refresh sequence. Only engine/collection services are mocked.
        g.write(g.base+0x8bf670,pe.get_data(0x8bf670,0x22e))
        g.write(g.base+0x8c0499,pe.get_data(0x8c0499,0x96))
        ui=g.obj(0x80);g.ptr(inv+0x40,ui)
        calls=[];delegate_actor=g.obj(0x40)
        def info():
            out,actor,*_=g.args();value=Information()
            value.number=0 if actor==g.actor1 else 1
            g.write(out,bytes(value));g.ret(out)
        def instantiate():g.ret(delegate_actor)
        def constructor():g.ret()
        def first():
            # The predicate is separately executed as native code in this test.
            g.ret(clone if g.state(48)==3 else g.actor2)
        def trinkets():
            actor=g.r('rcx');calls.append(('trinkets',actor));g.ret(actor+0x180)
        def refresh():calls.append(('refresh',g.r('rdx')));g.ret()
        g.callbacks.update({0x397da0:instantiate,0x3f3b70:constructor,
            0x677e00:first,0x186eb60:lambda:g.ret(g.r('rcx')!=g.r('rdx')),
            0x186ea90:lambda:g.ret(bool(g.r('rcx'))),
            0x74bbc0:lambda:g.ret(),0x74bab0:lambda:g.ret(),
            0x80cfb0:lambda:g.ret(),0x74b570:trinkets,0x8c0860:refresh,
            0x91c420:info})
        # Discover referenced metadata globals directly from the real code.
        import capstone
        md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);md.detail=True
        for ins in md.disasm(pe.get_data(0x8bf670,0x22e),0x8bf670):
            for op in ins.operands:
                if op.type==capstone.x86.X86_OP_MEM and op.mem.base==capstone.x86.X86_REG_RIP:
                    address=g.base+ins.address+ins.size+op.mem.disp
                    if op.size==8:g.ptr(address,g.obj(0x200))
        g.i32(g.base+MANIFEST['data_rva']+48,3)
        # Drop stub registration so the real LinkToPlayer runs.
        del g.callbacks[0x8bf670]
        for actor in g.actors:
            g.call('third_inventory_match',inv,actor,0)
            self.assertEqual(g.r('rax')&255,actor==clone)
        g.call(0x8bf670,inv,0,0,0)
        self.assertEqual(g.ptr(inv+0xc0),clone)
        self.assertEqual(calls,[('trinkets',clone),('refresh',clone+0x180)])

        # Rebind back through the actual native LinkToPlayer after P2 is replaced.
        replacement=g.obj(0x200);g.ptr(replacement+0x168,g.obj(0x40))
        g.actor2=replacement;g.actors=[g.actor1,clone,replacement]
        g.inventory_button(replacement,True)
        g.call('third_inventory_update',inv,0)
        self.assertEqual(g.ptr(inv+0xc0),replacement)
        self.assertEqual(g.read(inv+0x90,1),b'\1')
        self.assertEqual(g.read(replacement+0x111,1),b'\1')
        self.assertEqual(calls[-2:],[('trinkets',replacement),('refresh',replacement+0x180)])

    def test_save_count_leaves_gameplay_collection_intact(self):
        for count in [0,1,2,3,4]:
            g=Game();g.actors=[g.actor1]*count
            g.call('third_save_count',g.obj(0x30),0)
            self.assertEqual(g.r('rax'),min(count,2))
            self.assertEqual(len(g.actors),count)
    @unittest.skipUnless(HAS_GAME_DLL, GAME_DLL_REASON)
    def test_native_save_character_loop_reproduces_and_fixes_exception(self):
        import os
        dll=Path(os.environ.get('SOF_TEST_DLL','GameAssembly.dll')).read_bytes()
        for fixed in [False,True]:
            g=Game();g.start();g.press(7);g.native_integration=True
            image=patch.build_patch(dll) if fixed else dll
            pe=pefile.PE(data=image,fast_load=True)
            g.write(g.base+0x6c561b,pe.get_data(0x6c561b,0x13f))
            state=g.obj(0x300);data=g.obj(0x100);old_fools=g.obj(0x30)
            g.ptr(state+0x210,g.scene);g.ptr(state+0x1f8,g.ps)
            g.ptr(state+0x1c0,data);g.ptr(data+0xa0,old_fools)
            output=[];failure=[]
            def add_fool():output.append(g.r('rdx'));g.ret()
            def fail():failure.append('IndexOutOfRangeException');g.u.emu_stop()
            g.callbacks.update({0x6de9e0:lambda:g.ret(g.scene),
                0x24656d0:add_fool,0x6c6189:fail,0x6c6199:fail,
                0x6c575a:lambda:g.u.emu_stop()})
            g.setr('rsp',g.stack+0x1ff000);g.setr('rbp',state)
            g.setr('rbx',state+0x1c0);g.setr('r14',g.obj(0x30))
            for r in ['r12','rdi','rsi']:g.setr(r,0)
            g.setr('rcx',g.scene)
            g.u.emu_start(g.base+0x6c561b,g.base+0x6c6200,count=2000)
            self.assertEqual(output,[10,11])
            self.assertEqual(bool(failure),not fixed)
    def test_runtime_input_slot_clones_pad_maps(self):
        g=Game();manager=g.obj(0x80);user=g.obj(0x180);list=g.obj(0x30);items=g.obj(0x60)
        g.ptr(manager+0x20,user);g.ptr(user+0x18,list);g.ptr(list+0x10,items)
        g.i32(list+0x18,4);g.i32(user+0x118,7)
        editors=[]
        for i in range(4):
            p=g.obj(0x70);maps=g.obj(0x30);g.ptr(p+0x30,maps)
            g.i32(maps+0x18,3 if i>1 else 0);g.i32(p+0x10,[9999999,1,4,5][i])
            g.ptr(items+0x20+i*8,p);editors.append(p)
        g.call('third_input_awake',manager,0)
        self.assertEqual(g.i32(list+0x18),5)
        added=g.ptr(items+0x20+4*8)
        self.assertEqual(g.i32(added+0x10),7)
        self.assertEqual(g.ptr(added+0x30),g.ptr(editors[3]+0x30))
        self.assertEqual(g.i32(editors[3]+0x10),5)
        self.assertEqual(g.read(added+0x28,1),b'\1')
        self.assertEqual(g.read(added+0x58,3),b'\0'*3)
        # A second Awake must not add another input slot.
        g.call('third_input_awake',manager,0);self.assertEqual(g.i32(list+0x18),5)

@unittest.skipUnless(HAS_GAME_DLL, GAME_DLL_REASON)
class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Supply the baseline as an argument via environment to avoid bundling it.
        import os
        cls.baseline_path=Path(os.environ.get('SOF_TEST_DLL','GameAssembly.dll'))
        cls.baseline=cls.baseline_path.read_bytes()
        cls.patched=patch.build_patch(cls.baseline)

    def test_sections_and_original_exception_records(self):
        before=pefile.PE(data=self.baseline,fast_load=True)
        after=pefile.PE(data=self.patched,fast_load=True)
        self.assertEqual(len(after.sections),len(before.sections)+3)
        self.assertEqual([s.Characteristics for s in after.sections[-3:]],
                         [0x60000020,0xc0000040,0x40000040])
        old=before.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        new=after.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        old_bytes=before.get_data(old.VirtualAddress,old.Size)
        new_bytes=after.get_data(new.VirtualAddress,new.Size)
        self.assertEqual(new_bytes[:len(old_bytes)],old_bytes)
        self.assertEqual(new.Size,old.Size+12*len(MANIFEST['functions']))
        records=list(struct.iter_unpack('<III',new_bytes))
        self.assertEqual(records,sorted(records,key=lambda r:r[0]))
        for begin,end,unwind in records[-len(MANIFEST['functions']):]:
            self.assertLess(begin,end);self.assertEqual(after.get_data(unwind,1),b'\1')
        self.assertEqual(after.OPTIONAL_HEADER.SizeOfImage%0x1000,0)
        for a,b in zip(after.sections,after.sections[1:]):
            self.assertEqual(patch.align(a.VirtualAddress+a.Misc_VirtualSize,0x1000),b.VirtualAddress)

    def test_hook_targets_and_normal_ship_cleanup(self):
        p=pefile.PE(data=self.patched,fast_load=True)
        for rva,name in [(0x6dde70,'third_spawn'),(0x925a20,'third_reset'),
                         (0x6dd430,'third_despawn'),(0x1187030,'third_input_awake'),
                         (0x8fed9a,'third_dispatch'),(0x8c0e90,'third_inventory_update'),
                         (0x8c0490,'third_inventory_match')]+[(r,'third_save_count') for r in
                         [0x6c5331,0x6c5389,0x6c563e,0x6c5696]]:
            code=p.get_data(rva,5)
            self.assertEqual(rva+5+struct.unpack('<i',code[1:])[0],MANIFEST['symbols'][name]['rva'])
        for off,size in [(0x7a5dd9,5),(0x260d810,102),(0x258,4)]:
            self.assertEqual(self.patched[off:off+size],self.baseline[off:off+size])
        # All original executable sections are byte-identical outside the verified hooks.
        original=bytearray(self.baseline)
        for rva,size in [(0x6dde70,5),(0x925a20,6),(0x6dd430,6),(0x1187030,6),(0x8fed9a,5),(0x8c0e90,5),(0x8c0490,9)]+[(r,5) for r in [0x6c5331,0x6c5389,0x6c563e,0x6c5696]]:
            off=p.get_offset_from_rva(rva);original[off:off+size]=self.patched[off:off+size]
        for s in p.sections[:2]:
            off,size=s.PointerToRawData,s.SizeOfRawData
            self.assertEqual(bytes(original[off:off+size]),self.patched[off:off+size])

    def test_apply_check_restore_and_unknown_dll(self):
        with tempfile.TemporaryDirectory() as tmp:
            dll=Path(tmp)/'GameAssembly.dll';dll.write_bytes(self.baseline)
            script=ROOT.parent/'patch_third_player.py'
            def run(action,expected=0):
                r=subprocess.run([sys.executable,str(script),action,'--dll',str(dll)],capture_output=True,text=True)
                self.assertEqual(r.returncode,expected,r.stdout+r.stderr)
                return r.stdout
            self.assertIn('not installed',run('check'))
            run('apply');self.assertEqual(dll.read_bytes(),self.patched)
            self.assertIn('INSTALLED',run('check'));run('apply')
            run('restore');self.assertEqual(dll.read_bytes(),self.baseline)
            self.assertEqual(dll.with_name(dll.name+'.backup-before-3-player-mod').read_bytes(),self.baseline)
            corrupt=bytearray(self.baseline);corrupt[0x1000]^=1;dll.write_bytes(corrupt)
            run('apply',1);self.assertEqual(dll.read_bytes(),corrupt)

if __name__=='__main__':unittest.main(verbosity=2)
