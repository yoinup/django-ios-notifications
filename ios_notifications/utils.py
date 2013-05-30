# coding=utf-8


def is_sequence(arg):
    """
        Check if arg is a sequence
    """
    return (not hasattr(arg, "strip") and
            hasattr(arg, "__getitem__") or
            hasattr(arg, "__iter__"))