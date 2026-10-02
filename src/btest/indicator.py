class Indicator:
    """Subclass, set params, and return {line_name: array} from compute(). Arrays must be as
    long as the candles; use NaN where there is no value yet."""

    params: dict = {}
    pane: str = "price"
    levels: list = []

    def __init__(self, **params):
        unknown = set(params) - set(type(self).params)
        if unknown:
            raise ValueError(f"unknown params for {type(self).__name__}: {sorted(unknown)}")
        self.params = {**type(self).params, **params}

    def compute(self, c: dict) -> dict:
        raise NotImplementedError
