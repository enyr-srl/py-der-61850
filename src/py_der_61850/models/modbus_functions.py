from enum import Enum


class ModbusFunction(str, Enum):
    IEE754_BIG_ENDIAN = "iee754_big_endian"
    IEE754_LITTLE_ENDIAN = "iee754_little_endian"
    MULTIPLIER = "multiplier"
    WORD_SWAP = "word_swap"
    WORD_NORMAL = "word_normal"
