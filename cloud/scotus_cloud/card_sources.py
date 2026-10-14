"""Printed PDF page labels from the annotation prototype."""
import re

def printed_page_label(words, width, height, fallback=None):
    # Court ECF stamps contain "Document 27 ... Page 6 of 49" at the very top.
    # Those numbers are not the brief/appendix's printed pagination.
    top = [w for w in words if 20 < w["box"][1] < height*.12]
    # Appendix numbers ("17a", "-App. 17a-"); booklet pages centred on letter paper put them lower.
    upper = [w for w in words if 20 < w["box"][1] < height*.17]
    appendix = [w["text"].strip("-") for w in upper if re.fullmatch(r"\d+[a-z]",w["text"].strip("-"),re.I)]
    if appendix: return appendix[0]
    centered = lambda w: abs((w["box"][0]+w["box"][2])/2-width/2) < 25
    headers = [w["text"] for w in top if centered(w) and re.fullmatch(r"\d+|[ivxlcdm]+",w["text"],re.I)]
    footers = [w["text"] for w in words if centered(w) and w["box"][1] > height*.87 and re.fullmatch(r"\d+[a-z]?|[ivxlcdm]+",w["text"],re.I)]
    return (headers+footers)[0] if headers or footers else fallback
