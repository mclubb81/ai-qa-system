from pydantic import BaseModel


class RetrievedDoc(BaseModel):
    text: str
    source: str
    score: float


class SimilarBug(BaseModel):
    id: str
    title: str
    description: str
    severity: str
    score: float
