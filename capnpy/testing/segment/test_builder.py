import pytest
import struct
from capnpy.segment.builder import SegmentBuilder

@pytest.mark.skipif(getattr(SegmentBuilder, 'WIP', False), reason='WIP')
class TestSegmentBuilder(object):

    def test_allocate(self):
        buf = SegmentBuilder(16)
        assert buf.allocate(8) == 0
        s = buf.as_string()
        assert s == '\x00' * 8

    def test_write_int64(self):
        buf = SegmentBuilder(8)
        buf.allocate(8)
        buf.write_int64(0, 0x1234ABCD)
        s = buf.as_string()
        assert s == '\xCD\xAB\x34\x12\x00\x00\x00\x00'

    def test_alloc_struct(self):
        buf = SegmentBuilder(64)
        buf.allocate(16)
        a = buf.alloc_struct(0, data_size=3, ptrs_size=0)
        b = buf.alloc_struct(8, data_size=1, ptrs_size=0)
        buf.write_int64(a,    1)
        buf.write_int64(a+8,  2)
        buf.write_int64(a+16, 3)
        buf.write_int64(b,    4)
        s = buf.as_string()
        assert s == ('\x04\x00\x00\x00\x03\x00\x00\x00'   # ptr to a (3, 0)
                     '\x0c\x00\x00\x00\x01\x00\x00\x00'   # ptr to b (1, 0)
                     '\x01\x00\x00\x00\x00\x00\x00\x00'   # a: 1
                     '\x02\x00\x00\x00\x00\x00\x00\x00'   #    2
                     '\x03\x00\x00\x00\x00\x00\x00\x00'   #    3
                     '\x04\x00\x00\x00\x00\x00\x00\x00')  # b: 4

    def test_resize(self):
        buf = SegmentBuilder()
        buf.allocate(64)
        print
        buf.write_int64(0, 42)
        for i in range(63):
            buf.allocate(64)
        s = buf.as_string()
        assert len(s) == 64*64
        assert s[:8] == struct.pack('q', 42)
        assert s[8:] == '\x00' * (64*64-8)

    def test_resize_big_allocation(self):
        buf = SegmentBuilder(32)
        assert buf.length == 32
        assert buf.end == 0
        # make a big allocation, which is bigger than the normal exponential
        # growth of the buffer
        buf.allocate(4096)
        assert buf.length == 4096
        assert buf.end == 4096

