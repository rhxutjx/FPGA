"""Small ctypes binding to the supplied AArch64 RKNN MatMul C ABI.

This gate is separate from the eventual production NPU backend. No CPU fallback.
ABI source hashes are recorded by tools/prepare_rknn_sdk.py.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

Context = C.c_uint64  # supplied rknn_api.h: non-__arm__ builds, including AArch64
INT8, INT32, INT8_TO_INT32 = 2, 6, 2
TO_DEVICE, FROM_DEVICE, SDK_VERSION = 1, 2, 5
# Experimental gate choice, based on the board's successful native Q control.
# Never replace the private SDK or the board's library; load this absolute path.
SYSTEM_RUNTIME = Path("/usr/lib/librknnrt.so")
SYSTEM_RUNTIME_SHA256 = "73993ed4b440460825f21611731564503cc1d5a0c123746477da6cd574f34885"
EXPECTED_HEADERS = {
    "include/rknn_api.h": "eeb7260a8439e7c8894a704502ea640878c92aa956fafac18136b0784e2228cb",
    "include/rknn_matmul_api.h": "563bfb6a9801988683367a43fef9d71891a171febaba4d9ddd5041c46535c8c8",
}


class MatmulInfo(C.Structure):
    _fields_ = [("M",C.c_int32),("K",C.c_int32),("N",C.c_int32),("type",C.c_int),
                ("B_layout",C.c_int16),("B_quant_type",C.c_int16),
                ("AC_layout",C.c_int16),("AC_quant_type",C.c_int16),
                ("iommu_domain_id",C.c_int32),("group_size",C.c_int16),("reserved",C.c_int8*34)]


class TensorAttr(C.Structure):
    _fields_ = [("name",C.c_char*256),("n_dims",C.c_uint32),("dims",C.c_uint32*16),
                ("size",C.c_uint32),("type",C.c_int)]


class IOAttr(C.Structure):
    _fields_ = [("A",TensorAttr),("B",TensorAttr),("C",TensorAttr)]


class TensorMemory(C.Structure):
    _fields_ = [("virt_addr",C.c_void_p),("phys_addr",C.c_uint64),("fd",C.c_int32),
                ("offset",C.c_int32),("size",C.c_uint32),("flags",C.c_uint32),("priv_data",C.c_void_p)]


class SDKVersion(C.Structure):
    _fields_ = [("api_version",C.c_char*256),("drv_version",C.c_char*256)]


def abi_sizes():
    expected = {MatmulInfo:64, TensorAttr:332, IOAttr:996, TensorMemory:40, SDKVersion:512}
    if C.sizeof(C.c_void_p) != 8 or sys.byteorder != "little":
        raise RuntimeError("Binding requires a little-endian 64-bit process")
    for cls, size in expected.items():
        if C.sizeof(cls) != size:
            raise RuntimeError(f"ABI size mismatch for {cls.__name__}")
    return {cls.__name__: C.sizeof(cls) for cls in expected}


def verify_sdk(sdk):
    manifest = json.loads((sdk / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in EXPECTED_HEADERS.items():
        actual = hashlib.sha256((sdk / name).read_bytes()).hexdigest()
        if actual != expected or manifest["files"][name]["sha256"] != expected:
            raise RuntimeError(f"Binding does not match supplied SDK header: {name}")
    library = sdk / "lib/librknnrt.so"
    raw = library.read_bytes()
    # ELF64, little endian, AArch64 e_machine=183. Do not load arbitrary PC stubs.
    if raw[:6] != b"\x7fELF\x02\x01" or int.from_bytes(raw[18:20], "little") != 183:
        raise RuntimeError("Expected the supplied Linux AArch64 librknnrt.so")
    if hashlib.sha256(raw).hexdigest() != manifest["files"]["lib/librknnrt.so"]["sha256"]:
        raise RuntimeError("Runtime library hash differs from SDK manifest")
    return library, manifest


def check(operation, code):
    if code != 0:
        raise RuntimeError(f"{operation} failed: RKNN return code {code}")


def verify_system_runtime():
    raw = SYSTEM_RUNTIME.read_bytes()
    if raw[:6] != b"\x7fELF\x02\x01" or int.from_bytes(raw[18:20], "little") != 183:
        raise RuntimeError("System runtime must be a Linux AArch64 ELF64 library")
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != SYSTEM_RUNTIME_SHA256:
        raise RuntimeError("System runtime differs from the board-verified 2.3.0 hash; stop")
    return SYSTEM_RUNTIME, {"source":"board_existing_system_library", "path":str(SYSTEM_RUNTIME.resolve()),
                            "sha256":actual_hash, "expected_api":"2.3.0", "expected_driver":"0.9.8"}


class RKNNMatmul:
    def __init__(self, sdk: Path, k: int, n: int, weights: bytes, *, batch: int = 1, system_runtime=False):
        self.ctx, self.created, self.memories = Context(), False, []
        self.k, self.n, self.batch = k, n, batch
        self.calls = {"context_creations":0, "weight_uploads":0, "run_calls":0}
        self.abi = abi_sizes()
        if platform.system() != "Linux" or platform.machine().lower() not in ("aarch64", "arm64"):
            raise RuntimeError("Real RKNN gate must run on Linux AArch64; no mock/CPU fallback")
        library, self.sdk_manifest = verify_sdk(sdk)
        self.runtime_selection = {"source":"supplied_sdk_private", "path":str(library.resolve()),
                                  "sha256":self.sdk_manifest.get("files",{}).get("lib/librknnrt.so",{}).get("sha256")}
        if system_runtime:
            library, self.runtime_selection = verify_system_runtime()
        self.library_path = str(library.resolve())
        self.lib = C.CDLL(str(library))
        self._bind()
        if len(weights) != k*n:
            raise ValueError("INT8 B[K,N] byte count mismatch")
        self.info, self.attrs = MatmulInfo(), IOAttr()
        self.info.M, self.info.K, self.info.N, self.info.type = batch, k, n, INT8_TO_INT32
        # normal B[K,N], normal A/C, raw INT8 dot product; not a production quantization choice
        start = time.perf_counter_ns()
        check("rknn_matmul_create", self.lib.rknn_matmul_create(C.byref(self.ctx), C.byref(self.info), C.byref(self.attrs)))
        self.created = True
        self.calls["context_creations"] = 1
        self.create_us = (time.perf_counter_ns()-start)/1000
        try:
            version = SDKVersion()
            check("rknn_query(SDK_VERSION)", self.lib.rknn_query(self.ctx, SDK_VERSION, C.byref(version), C.sizeof(version)))
            self.versions = {"api":version.api_version.decode(errors="replace"), "driver":version.drv_version.decode(errors="replace")}
            if not all(self.versions.values()):
                raise RuntimeError("Empty API/driver version: hardware evidence incomplete")
            if system_runtime and (self.versions["api"].split()[:1] != ["2.3.0"] or self.versions["driver"] != "0.9.8"):
                raise RuntimeError(f"System runtime query differs from verified native control: {self.versions}")
            start = time.perf_counter_ns()
            for attr, minimum, dtype, shape in ((self.attrs.A,batch*k,INT8,[batch,k]),(self.attrs.B,k*n,INT8,[k,n]),(self.attrs.C,batch*n*4,INT32,[batch,n])):
                if attr.type != dtype or not 0 < attr.n_dims <= 16 or any(d == 0 for d in attr.dims[:attr.n_dims]):
                    raise RuntimeError(f"Unexpected returned dtype/shape: {self.attr_dict(attr)}")
                if list(attr.dims[:attr.n_dims]) != shape:
                    raise RuntimeError(f"Unexpected normal-layout dimensions: {self.attr_dict(attr)}; expected {shape}")
                if not minimum <= attr.size <= max(16*1024*1024, minimum*2):
                    raise RuntimeError(f"Unexpected returned buffer size: {self.attr_dict(attr)}")
                memory = self.lib.rknn_create_mem(self.ctx, attr.size)
                if not memory:
                    raise RuntimeError(f"rknn_create_mem returned NULL for {attr.size} bytes")
                self.memories.append(memory)
                if not memory.contents.virt_addr or memory.contents.size < attr.size:
                    raise RuntimeError("Invalid allocated RKNN buffer")
                # v10 diagnostic only: skip CPU initialization of output C.
                if dtype != INT32:
                    C.memset(memory.contents.virt_addr, 0, attr.size)
                if memory.contents.offset != 0:
                    raise RuntimeError("Unexpected offset for rknn_create_mem; refusing ambiguous buffer addressing")
            C.memmove(self.memories[1].contents.virt_addr, weights, len(weights))
            check("weight sync TO_DEVICE", self.lib.rknn_mem_sync(self.ctx, self.memories[1], TO_DEVICE))
            self.calls["weight_uploads"] = 1
            # Normal-layout B may be transformed/snapshotted by set_io_mem.
            # Populate and sync BEFORE binding, as in the official MatMul demo.
            for memory,attr in zip(self.memories,(self.attrs.A,self.attrs.B,self.attrs.C)):
                check("rknn_matmul_set_io_mem", self.lib.rknn_matmul_set_io_mem(self.ctx,memory,C.byref(attr)))
            self.setup_us = (time.perf_counter_ns()-start)/1000
        except BaseException:
            self.close()
            raise

    def _bind(self):
        mem = C.POINTER(TensorMemory)
        definitions = {
            "rknn_matmul_create": ([C.POINTER(Context),C.POINTER(MatmulInfo),C.POINTER(IOAttr)],C.c_int),
            "rknn_query": ([Context,C.c_int,C.c_void_p,C.c_uint32],C.c_int),
            "rknn_create_mem": ([Context,C.c_uint32],mem),
            "rknn_matmul_set_io_mem": ([Context,mem,C.POINTER(TensorAttr)],C.c_int),
            "rknn_mem_sync": ([Context,mem,C.c_int],C.c_int),
            "rknn_matmul_run": ([Context],C.c_int),
            "rknn_destroy_mem": ([Context,mem],C.c_int),
            "rknn_matmul_destroy": ([Context],C.c_int),
        }
        for name,(args,result) in definitions.items():
            try:
                fn = getattr(self.lib,name)
            except AttributeError as exc:
                raise RuntimeError(f"Required runtime symbol missing: {name}") from exc
            fn.argtypes, fn.restype = args, result

    @staticmethod
    def attr_dict(attr):
        return {"name":attr.name.decode(errors="replace"), "shape":list(attr.dims[:min(attr.n_dims,16)]),
                "bytes":attr.size, "rknn_dtype":attr.type}

    def run(self, inputs):
        if len(inputs) != self.batch * self.k:
            raise ValueError("INT8 A[1,K] byte count mismatch")
        start = time.perf_counter_ns()
        C.memmove(self.memories[0].contents.virt_addr, inputs, len(inputs))
        check("input sync TO_DEVICE", self.lib.rknn_mem_sync(self.ctx,self.memories[0],TO_DEVICE))
        after_input_sync = time.perf_counter_ns()
        # Refresh normal-layout A AFTER its new bytes arrive. Reuse B/context;
        # never rely on a prior binding retaining a live view of changed A.
        check("input rknn_matmul_set_io_mem",self.lib.rknn_matmul_set_io_mem(self.ctx,self.memories[0],C.byref(self.attrs.A)))
        before_run = time.perf_counter_ns()
        check("rknn_matmul_run", self.lib.rknn_matmul_run(self.ctx))
        self.calls["run_calls"] += 1
        after_run = time.perf_counter_ns()
        check("output sync FROM_DEVICE", self.lib.rknn_mem_sync(self.ctx,self.memories[2],FROM_DEVICE))
        after_sync = time.perf_counter_ns()
        output = C.string_at(self.memories[2].contents.virt_addr,self.batch*self.n*4)
        end = time.perf_counter_ns()
        return output, {"input_copy_sync_us":(after_input_sync-start)/1000,"input_bind_us":(before_run-after_input_sync)/1000,
                        "run_api_us":(after_run-before_run)/1000,
                        "output_sync_us":(after_sync-after_run)/1000, "step_us":(end-start)/1000}

    def close(self):
        errors = []
        if self.created:
            for memory in reversed(self.memories):
                code = self.lib.rknn_destroy_mem(self.ctx,memory)
                if code: errors.append(f"rknn_destroy_mem={code}")
            self.memories.clear()
            code = self.lib.rknn_matmul_destroy(self.ctx)
            if code: errors.append(f"rknn_matmul_destroy={code}")
            self.created = False
        return errors
