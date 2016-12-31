import struct
import capnpy
from capnpy.blob import Blob, Types
from capnpy import ptr
from capnpy import listbuilder
from capnpy.util import text_repr, float32_repr, float64_repr

class List(Blob):

    @classmethod
    def from_buffer(cls, buf, offset, size_tag, item_count, item_type):
        """
        buf, offset: the underlying buffer and the offset where the list starts

        item_length: the length of each list item, in BYTES. Note: this is NOT the
        value of the ListPtr.SIZE_* tag, although it's obviously based on it

        item_type: an instance of a subclass of ItemType
        """
        self = cls.__new__(cls)
        self._init_from_buffer(buf, offset, size_tag, item_count, item_type)
        return self

    def _init_from_buffer(self, buf, offset, size_tag, item_count, item_type):
        self._init_blob(buf)
        self._offset = offset
        self._item_type = item_type
        self._set_list_tag(size_tag, item_count)

    def __reduce__(self):
        raise TypeError("Cannot pickle capnpy List directly. Either pickle "
                        "the outer structure containing it, or convert it "
                        "to a Python list before pickling")

    def _read_ptr_generic(self, offset):
        offset += self._offset
        return offset, self._buf.read_ptr(offset)

    def _set_list_tag(self, size_tag, item_count):
        self._size_tag = size_tag
        if size_tag == ptr.LIST_SIZE_COMPOSITE:
            tag = self._buf.read_raw_ptr(self._offset)
            self._tag = tag
            self._item_count = ptr.offset(tag)
            self._item_length = (ptr.struct_data_size(tag)+ptr.struct_ptrs_size(tag))*8
            self._item_offset = 8
        elif size_tag == ptr.LIST_SIZE_BIT:
            raise ValueError('Lists of bits are not supported')
        else:
            self._tag = -1
            self._item_count = item_count
            self._item_length = ptr.LIST_SIZE_LENGTH[size_tag]
            self._item_offset = 0

    def __repr__(self):
        return '<capnpy list [%d items]>' % (len(self),)

    def _get_offset_for_item(self, i):
        return self._item_offset + (i*self._item_length)
            
    def __len__(self):
        return self._item_count

    def __getitem__(self, i):
        if isinstance(i, slice):
            idx = xrange(*i.indices(len(self)))
            return [self._getitem_fast(j) for j in idx]
        if i < 0:
            i += self._item_count
        if 0 <= i < self._item_count:
            return self._getitem_fast(i)
        raise IndexError

    def _getitem_fast(self, i):
        """
        WARNING: no bound checks!
        """
        offset = self._get_offset_for_item(i)
        return self._item_type.read_item(self, offset)

    def _get_body_range(self):
        return self._get_body_start(), self._get_body_end()

    def _get_body_start(self):
        return self._offset

    def _get_body_end(self):
        if self._size_tag == ptr.LIST_SIZE_COMPOSITE:
            return self._get_body_end_composite()
        elif self._size_tag == ptr.LIST_SIZE_PTR:
            return self._get_body_end_ptr()
        else:
            return self._get_body_end_scalar()

    def _get_body_end_composite(self):
        # lazy access to Struct to avoid circular imports
        Struct = capnpy.struct_.Struct
        #
        # to calculate the end the of the list, there are three cases
        #
        # 1) if the items has no pointers, the end of the list correspond
        #    to the end of the items
        #
        # 2) if they HAVE pointers but they are ALL null, it's the same as (1)
        #
        # 3) if they have pointers, the end of the list is at the end of
        #    the extra of the latest item having a pointer field set

        if ptr.struct_ptrs_size(self._tag) == 0:
            # case 1
            return self._get_body_end_scalar()+8 # +8 is for the tag

        i = self._item_count-1
        while i >= 0:
            struct_offset = self._get_offset_for_item(i)
            struct_offset += self._offset
            mystruct = Struct.from_buffer(self._buf,
                                          struct_offset,
                                          ptr.struct_data_size(self._tag),
                                          ptr.struct_ptrs_size(self._tag))
            end = mystruct._get_extra_end_maybe()
            if end is not None:
                # case 3
                return end
            i -= 1

        # case 2
        return self._get_body_end_scalar()+8 # +8 is for the tag

    def _get_body_end_ptr(self):
        ptr_offset = self._get_offset_for_item(self._item_count-1)
        blob = self._read_list_or_struct(ptr_offset)
        return blob._get_end()

    def _get_body_end_scalar(self):
        return self._offset + self._item_length*self._item_count

    def _get_end(self):
        return self._get_body_end()

    def _get_key(self):
        start, end = self._get_body_range()
        body = self._buf.s[start:end]
        return (self._item_count, self._item_type, body)

    def _equals(self, other):
        if not self._item_type.can_compare():
            raise TypeError("Cannot compare lists of structs.")
        if isinstance(other, list):
            return list(self) == other
        if self.__class__ is not other.__class__:
            return False
        return self._get_key() == other._get_key()

    def shortrepr(self):
        parts = [self._item_repr(item) for item in self]
        return '[%s]' % (', '.join(parts))


class ItemType(object):

    def read_item(self, lst, offset):
        raise NotImplementedError

    def item_repr(self, item):
        raise NotImplementedError

    def can_compare(self):
        return True


class PrimitiveItemType(ItemType):
    ItemBuilder = listbuilder.PrimitiveItemBuilder

    def __init__(self, t):
        self.t = t
        self.ifmt = t.ifmt

    def read_item(self, lst, offset):
        return lst._buf.read_primitive(lst._offset+offset, self.ifmt)

    def item_repr(self, item):
        if self.t is Types.float32:
            return float32_repr(item)
        elif self.t is Types.float64:
            return float64_repr(item)
        else:
            return repr(item)


class StructItemType(ItemType):
    ItemBuilder = listbuilder.StructItemBuilder

    def __init__(self, structcls):
        self.structcls = structcls

    def can_compare(self):
        return False

    def read_item(self, lst, offset):
        return self.structcls.from_buffer(lst._buf,
                                          lst._offset+offset,
                                          ptr.struct_data_size(lst._tag),
                                          ptr.struct_ptrs_size(lst._tag))

    def item_repr(self, item):
        return item.shortrepr()


class TextItemType(ItemType):
    ItemBuilder = listbuilder.StringItemBuilder

    def read_item(self, lst, offset):
        offset += lst._offset
        p = lst._buf.read_ptr(offset)
        if p == ptr.E_IS_FAR_POINTER:
            raise NotImplementedError('FAR pointers not supported here')
        return lst._buf.read_str(p, offset, None, -1)

    def item_repr(self, item):
        return text_repr(item)



# set the list_item_type attribute of Types.*
def fill_types_item_type():
    Types.text.list_item_type = TextItemType()
    for t in Types.__all__:
        if t.is_primitive():
            t.list_item_type = PrimitiveItemType(t)
fill_types_item_type()
del fill_types_item_type


# temporary compatibility with the old schema.py
def PrimitiveList():
    raise NotImplementedError

def StructList():
    raise NotImplementedError

def StringList():
    raise NotImplementedError
