"""Optional public-interface smoke tests; no hosted services or credentials."""
import importlib.util
import unittest
from rag_preflight import from_langchain_documents, from_llama_index_nodes


class FrameworkTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('langchain_core'), 'optional langchain-core')
    def test_real_langchain_document(self):
        from langchain_core.documents import Document
        document=Document(page_content='Example body',metadata={'source':'test','chunk_key':'stable'})
        result=from_langchain_documents([document])
        self.assertEqual(result[0]['text'],'Example body')
        self.assertEqual(result[0]['chunk_key'],'stable')
        self.assertNotIn('units',result[0]['metadata'])

    @unittest.skipUnless(importlib.util.find_spec('llama_index'), 'optional llama-index-core')
    def test_real_llama_text_node(self):
        from llama_index.core.schema import TextNode
        node=TextNode(text='Example body',metadata={'source':'test','chunk_key':'stable'})
        result=from_llama_index_nodes([node])
        self.assertEqual(result[0]['text'],'Example body')
        self.assertEqual(result[0]['chunk_key'],'stable')
        self.assertNotIn('source_version',result[0]['metadata'])

    @unittest.skipUnless(importlib.util.find_spec('langgraph'), 'optional langgraph')
    def test_real_graph_routes(self):
        from pathlib import Path
        import runpy
        runpy.run_path(str(Path(__file__).resolve().parents[1]/'examples/langgraph_gate.py'),run_name='__main__')
