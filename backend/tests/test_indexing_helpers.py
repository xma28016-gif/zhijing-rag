from app.services.indexing import segment_for_search


def test_chinese_search_segmentation_keeps_meaningful_terms() -> None:
    segmented = segment_for_search("企业知识库构建指南")
    assert "知识库" in segmented
    assert "构建" in segmented
