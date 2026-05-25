import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
import sqlite3
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from config import MEMORY_DIR

logger = logging.getLogger(__name__)


class MemPalace:
    """
    MemPalace — система долгосрочной памяти по архитектуре "Чертоги разума"
    Использует ChromaDB с SentenceTransformer для векторного поиска + SQLite для графа знаний
    """

    def __init__(self, user_id: int):
        """
        Инициализация памяти для конкретного пользователя
        Args:
            user_id: Telegram ID пользователя
        """
        self.user_id = user_id
        self.user_dir = MEMORY_DIR / str(user_id)
        self.user_dir.mkdir(parents=True, exist_ok=True)

        # ChromaDB для векторного поиска с SentenceTransformer
        try:
            self.chroma_client = chromadb.PersistentClient(
                path=str(self.user_dir / "chroma_db"),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )

            embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            self.collection = self.chroma_client.get_or_create_collection(
                name=f"user_{user_id}_memories",
                embedding_function=embedding_func,
                metadata={
                    "hnsw:space": "cosine",
                    "hnsw:construction_ef": 128,
                    "hnsw:search_ef": 128
                }
            )
            logger.info(f"ChromaDB initialized for user {user_id}")
        except Exception as e:
            logger.error(f"ChromaDB initialization error: {e}")
            self.collection = None
            logger.warning("Using fallback memory mode (SQLite only)")

        # SQLite для графа знаний (Temporal Knowledge Graph)
        self.graph_db = self.user_dir / "knowledge_graph.db"
        self._init_graph_db()

        # Кэш мета-информации (L0 слой — кто этот пользователь)
        self._user_meta = self._load_user_metadata()

    def _init_graph_db(self):
        """Инициализация SQLite для хранения графа знаний"""
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        # Таблица фактов с временными метками (Temporal KG)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            wing TEXT DEFAULT 'default',
            room TEXT DEFAULT 'default',
            hall TEXT DEFAULT 'hall_facts',
            valid_from TIMESTAMP,
            valid_to TIMESTAMP,
            confidence REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Таблица диалогов (interactions)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            response TEXT NOT NULL,
            wing TEXT DEFAULT 'default',
            room TEXT DEFAULT 'default',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_used INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0
        )
        """)

        # Таблица мета-информации о пользователе (L0 слой)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Индексы для быстрого поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_room ON facts(room)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(timestamp)")

        conn.commit()
        conn.close()
        logger.info(f"Graph DB initialized: {self.graph_db}")

    def _load_user_metadata(self) -> Dict:
        """Загрузка мета-информации пользователя (L0 слой Wake-Up)"""
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM user_meta")
        rows = cursor.fetchall()
        conn.close()

        meta = {row[0]: row[1] for row in rows}

        # Если мета пустая — создаём базовую
        if not meta:
            meta = {
                "user_id": str(self.user_id),
                "created_at": datetime.now().isoformat(),
                "total_interactions": "0",
                "active_projects": "default"
            }
            self._save_user_metadata(meta)

        return meta

    def _save_user_metadata(self, meta: Dict):
        """Сохранение мета-информации"""
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        for key, value in meta.items():
            cursor.execute("""
            INSERT OR REPLACE INTO user_meta (key, value, updated_at)
            VALUES (?, ?, ?)
            """, (key, str(value), datetime.now().isoformat()))

        conn.commit()
        conn.close()

    def wake_up(self, query: str, top_k: int = 5) -> str:
        """
        Wake-Up слой (L0+L1): загрузка контекста перед генерацией ответа
        Args:
            query: Текущий запрос пользователя
            top_k: Количество релевантных воспоминаний
        Returns:
            Компактный контекст для промпта
        """
        context_parts = []

        # L0: Мета-информация (Кто этот пользователь?)
        context_parts.append(f"👤 Пользователь #{self.user_id}")
        if self._user_meta.get("active_projects"):
            context_parts.append(f" Проекты: {self._user_meta['active_projects']}")

        # L1: Поиск релевантных фактов по векторам (ChromaDB)
        if self.collection and self.collection.count() > 0:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=min(top_k, self.collection.count()),
                    include=["documents", "metadatas", "distances"]
                )

                # Фильтруем по релевантности (distance < 1.5 для cosine similarity)
                for doc, meta, dist in zip(
                        results['documents'][0],
                        results['metadatas'][0],
                        results['distances'][0]
                ):
                    if dist < 1.5:
                        hall_type = meta.get('hall', 'facts')
                        context_parts.append(f"[{hall_type}]: {doc[:200]}")
            except Exception as e:
                logger.error(f"ChromaDB query error: {e}")

        # L1: Последние факты из графа (Temporal KG)
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        # Ищем факты по ключевым словам из запроса
        keywords = query.lower().split()[:3]
        for keyword in keywords:
            if len(keyword) > 3:
                cursor.execute("""
                SELECT subject, predicate, object, hall
                FROM facts
                WHERE (subject LIKE ? OR object LIKE ?)
                AND (valid_to IS NULL OR valid_to > ?)
                ORDER BY created_at DESC
                LIMIT 2
                """, (f'%{keyword}%', f'%{keyword}%', datetime.now().isoformat()))

                facts = cursor.fetchall()
                for subj, pred, obj, hall in facts:
                    context_parts.append(f"[{hall}]: {subj} {pred} {obj}")

        conn.close()

        # Ограничиваем размер контекста
        final_context = "\n".join(context_parts[:top_k + 2])
        logger.info(f"Wake-Up context: {len(final_context)} chars")

        return final_context

    # ==========================================
    # 🧠 МЕТОД ДЛЯ РЕЖИМА "ВСПОМНИ"
    # ==========================================
    def deep_remember(self, query: str, top_k: int = 15) -> str:
        """
        Глубокий поиск в архивах памяти (для команды "ВСПОМНИ").
        Расширенный поиск по векторам и фактам с более мягкими фильтрами.
        """
        context_parts = []

        # Заголовок для контекста
        context_parts.append(f"🔍 РЕЖИМ: ГЛУБОКИЙ ПОИСК В ПАМЯТИ\n")
        context_parts.append(f"👤 Пользователь #{self.user_id}\n")

        # 1. Расширенный векторный поиск (ChromaDB)
        if self.collection and self.collection.count() > 0:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=min(top_k * 2, self.collection.count()),
                    include=["documents", "metadatas", "distances"]
                )

                # Мягче порог релевантности (2.0 вместо 1.5)
                for doc, meta, dist in zip(
                        results['documents'][0],
                        results['metadatas'][0],
                        results['distances'][0]
                ):
                    if dist < 2.0:
                        hall_type = meta.get('hall', 'facts')
                        timestamp = meta.get('timestamp', '')[:10] if meta.get('timestamp') else '?'
                        context_parts.append(f"[{hall_type}|{timestamp}]: {doc[:300]}")
            except Exception as e:
                logger.error(f"Deep remember ChromaDB error: {e}")

        # 2. Глубокий поиск в графе знаний (SQLite)
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        # Ищем по всем значимым ключевым словам (длиннее 3 символов)
        keywords = [kw for kw in query.lower().split() if len(kw) > 3]

        if keywords:
            conditions = " OR ".join([
                f"(subject LIKE ? OR object LIKE ? OR predicate LIKE ?)"
                for _ in keywords
            ])

            params = []
            for kw in keywords:
                params.extend([f'%{kw}%', f'%{kw}%', f'%{kw}%'])

            params.append(datetime.now().isoformat())

            query_sql = f"""
            SELECT subject, predicate, object, hall, room, created_at
            FROM facts
            WHERE ({conditions})
            AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY created_at DESC
            LIMIT {top_k * 2}
            """

            cursor.execute(query_sql, params)

            for subj, pred, obj, hall, room, created in cursor.fetchall():
                date_str = created[:10] if created else '?'
                context_parts.append(f"[Факт|{hall}/{room}|{date_str}]: {subj} {pred} {obj}")

        conn.close()

        # Если ничего не нашли
        if len(context_parts) <= 2:
            return "🔍 В глубокой памяти не найдено записей по этому запросу."

        return "\n".join(context_parts[:top_k + 5])

    def store_interaction(self, query: str, response: str,
                          tokens_used: int = 0, latency_ms: int = 0,
                          wing: str = "default", room: str = "default"):
        """
        Сохранение диалога в память (MemPalace Storage)
        """
        # 1. Сохраняем в векторное хранилище (ChromaDB)
        if self.collection:
            try:
                hall = self._classify_hall(query, response)

                self.collection.add(
                    documents=[f"Q: {query}\nA: {response}"],
                    metadatas=[{
                        "type": "interaction",
                        "hall": hall,
                        "wing": wing,
                        "room": room,
                        "timestamp": datetime.now().isoformat(),
                        "tokens": tokens_used
                    }],
                    ids=[f"int_{datetime.now().timestamp()}_{hash(query) % 10000}"]
                )
                logger.debug(f"Stored interaction in ChromaDB: {query[:50]}...")
            except Exception as e:
                logger.error(f"ChromaDB store error: {e}")

        # 2. Сохраняем в граф знаний (SQLite)
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO interactions
        (query, response, wing, room, tokens_used, latency_ms, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (query, response, wing, room, tokens_used, latency_ms, datetime.now()))

        # 3. Извлекаем факты из ответа (простая эвристика)
        facts = self._extract_facts_from_response(query, response, wing, room)
        for subj, pred, obj, hall in facts:
            cursor.execute("""
            INSERT INTO facts (subject, predicate, object, wing, room, hall)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (subj, pred, obj, wing, room, hall))

        # 4. Обновляем счётчик взаимодействий
        cursor.execute("""
        INSERT OR REPLACE INTO user_meta (key, value, updated_at)
        VALUES ('total_interactions',
        COALESCE((SELECT value FROM user_meta WHERE key='total_interactions'), '0') + 1,
        ?)
        """, (datetime.now().isoformat(),))

        conn.commit()
        conn.close()

        # 5. Обновляем кэш мета-информации
        self._user_meta["total_interactions"] = str(
            int(self._user_meta.get("total_interactions", 0)) + 1
        )

        logger.info(f"Interaction stored: {query[:50]}...")

    def _classify_hall(self, query: str, response: str) -> str:
        """
        Классификация контента по Залам (Halls)
        """
        query_lower = query.lower()
        response_lower = response.lower()

        # hall_events: события, действия
        event_keywords = ['сделал', 'запустил', 'ошибка', 'дебаг', 'исправил',
                          'создал', 'удалил', 'обновил', 'отправил']
        if any(kw in query_lower or kw in response_lower for kw in event_keywords):
            return "hall_events"

        # hall_preferences: предпочтения
        pref_keywords = ['нравится', 'предпочитаю', 'хочу', 'люблю',
                         'не люблю', 'удобно', 'лучше']
        if any(kw in query_lower for kw in pref_keywords):
            return "hall_preferences"

        # По умолчанию — факты
        return "hall_facts"

    def _extract_facts_from_response(self, query: str, response: str,
                                     wing: str, room: str) -> List[Tuple[str, str, str, str]]:
        """
        Извлечение фактов из ответа (Temporal Knowledge Graph)
        """
        facts = []
        hall = self._classify_hall(query, response)

        # Простая эвристика: ищем паттерны "X это Y", "X = Y"
        import re

        # Паттерн: "X это Y" / "X - это Y"
        pattern_is = r'([А-Яа-яA-Za-z0-9_\-]+)\s+(?:это|- это)\s+([А-Яа-яA-Za-z0-9_\-\s]+?)(?:\.|$)'
        matches = re.findall(pattern_is, response)
        for subj, obj in matches:
            if len(subj) > 1 and len(obj) > 3:
                facts.append((subj.strip(), "is", obj.strip(), hall))

        # Паттерн: "X = Y" / "X: Y"
        pattern_eq = r'([А-Яа-яA-Za-z0-9_\-]+)\s*[:=]\s*([А-Яа-яA-Za-z0-9_\-\s]+?)(?:\.|$)'
        matches = re.findall(pattern_eq, response)
        for subj, obj in matches:
            if len(subj) > 1 and len(obj) > 2:
                facts.append((subj.strip(), "equals", obj.strip(), hall))

        return facts[:5]

    def add_fact(self, subject: str, predicate: str, obj: str,
                 wing: str = "default", room: str = "default",
                 hall: str = "hall_facts",
                 valid_from: datetime = None, valid_to: datetime = None,
                 confidence: float = 1.0):
        """
        Добавление факта в граф знаний (Temporal KG)
        """
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO facts
        (subject, predicate, object, wing, room, hall, valid_from, valid_to, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (subject, predicate, obj, wing, room, hall,
              valid_from or datetime.now(), valid_to, confidence))

        conn.commit()
        conn.close()
        logger.info(f"Fact added: {subject} {predicate} {obj}")

    def invalidate_facts(self, subject: str = None, room: str = None):
        """
        Инвалидация фактов (когда проект закрыт или данные устарели)
        """
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        conditions = []
        params = []

        if subject:
            conditions.append("subject = ?")
            params.append(subject)
        if room:
            conditions.append("room = ?")
            params.append(room)

        if conditions:
            query = f"""
            UPDATE facts
            SET valid_to = ?, updated_at = ?
            WHERE {' AND '.join(conditions)} AND valid_to IS NULL
            """
            params.extend([datetime.now(), datetime.now()])
            cursor.execute(query, params)
            conn.commit()
            logger.info(f"Invalidated {cursor.rowcount} facts")

        conn.close()

    def get_stats(self) -> Dict:
        """
        Получение статистики памяти (для админ-панели)
        """
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        # Общее количество взаимодействий
        cursor.execute("SELECT COUNT(*) FROM interactions")
        total_interactions = cursor.fetchone()[0]

        # Количество фактов по залам
        cursor.execute("""
        SELECT hall, COUNT(*)
        FROM facts
        WHERE valid_to IS NULL
        GROUP BY hall
        """)
        facts_by_hall = dict(cursor.fetchall())

        # Активные комнаты
        cursor.execute("""
        SELECT DISTINCT room
        FROM interactions
        WHERE timestamp > datetime('now', '-30 days')
        """)
        active_rooms = [row[0] for row in cursor.fetchall()]

        conn.close()

        # Количество векторов в ChromaDB
        vector_count = self.collection.count() if self.collection else 0

        return {
            "user_id": self.user_id,
            "total_interactions": total_interactions,
            "total_facts": sum(facts_by_hall.values()),
            "facts_by_hall": facts_by_hall,
            "vector_count": vector_count,
            "active_rooms": active_rooms[:10],
            "storage_size_mb": self._get_storage_size_mb()
        }

    def _get_storage_size_mb(self) -> float:
        """Получение размера хранилища в МБ"""
        total_size = 0

        # Размер ChromaDB
        chroma_path = self.user_dir / "chroma_db"
        if chroma_path.exists():
            for path in chroma_path.rglob('*'):
                if path.is_file():
                    total_size += path.stat().st_size

        # Размер SQLite
        if self.graph_db.exists():
            total_size += self.graph_db.stat().st_size

        return round(total_size / (1024 * 1024), 2)

    def search_memories(self, query: str, wing: str = None,
                        room: str = None, top_k: int = 10) -> List[Dict]:
        """
        Поиск воспоминаний (для MCP-интеграции и админки)
        """
        results = []

        # Поиск в векторном хранилище
        if self.collection and self.collection.count() > 0:
            where_clause = {}
            if wing:
                where_clause["wing"] = wing
            if room:
                where_clause["room"] = room

            try:
                chroma_results = self.collection.query(
                    query_texts=[query],
                    n_results=min(top_k, self.collection.count()),
                    where=where_clause if where_clause else None,
                    include=["documents", "metadatas", "distances"]
                )

                for doc, meta, dist in zip(
                        chroma_results['documents'][0],
                        chroma_results['metadatas'][0],
                        chroma_results['distances'][0]
                ):
                    results.append({
                        "type": "vector",
                        "document": doc,
                        "metadata": meta,
                        "distance": float(dist),
                        "relevance": 1.0 / (1.0 + dist)
                    })
            except Exception as e:
                logger.error(f"Vector search error: {e}")

        # Поиск в графе знаний (SQLite FTS)
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        sql_query = """
        SELECT 'fact' as type,
        subject || ' ' || predicate || ' ' || object as content,
        wing, room, hall, created_at,
        0.8 as relevance
        FROM facts
        WHERE (subject LIKE ? OR object LIKE ?)
        AND (valid_to IS NULL OR valid_to > ?)
        """
        params = [f'%{query}%', f'%{query}%', datetime.now().isoformat()]

        if wing:
            sql_query += " AND wing = ?"
            params.append(wing)
        if room:
            sql_query += " AND room = ?"
            params.append(room)

        sql_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(top_k)

        cursor.execute(sql_query, params)

        for row in cursor.fetchall():
            results.append({
                "type": row[0],
                "content": row[1],
                "wing": row[2],
                "room": row[3],
                "hall": row[4],
                "timestamp": row[5],
                "relevance": row[6]
            })

        conn.close()

        # Сортируем по релевантности
        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)

        return results[:top_k]

    def export_memory(self, format: str = "json") -> str:
        """
        Экспорт всей памяти пользователя (для бэкапа)
        """
        conn = sqlite3.connect(self.graph_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Экспортируем всё
        cursor.execute("SELECT * FROM interactions ORDER BY timestamp")
        interactions = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM facts WHERE valid_to IS NULL")
        facts = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM user_meta")
        meta = {row["key"]: row["value"] for row in cursor.fetchall()}

        conn.close()

        if format == "json":
            import json
            return json.dumps({
                "user_id": self.user_id,
                "exported_at": datetime.now().isoformat(),
                "meta": meta,
                "interactions": interactions,
                "facts": facts
            }, ensure_ascii=False, indent=2)

        elif format == "sql":
            dump = f"-- Memory export for user {self.user_id}\n"
            dump += f"-- Exported at {datetime.now().isoformat()}\n"

            for interaction in interactions:
                dump += f"INSERT INTO interactions VALUES ("
                dump += ", ".join(f"'{v}'" if isinstance(v, str) else str(v)
                                  for v in interaction.values())
                dump += ");\n"

            return dump

        return ""

    def cleanup_old_memories(self, days: int = 90):
        """
        Очистка старых воспоминаний (оптимизация хранилища)
        """
        cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)

        # Удаляем старые вектора из ChromaDB
        if self.collection:
            try:
                logger.info(f"Cleanup: keeping memories from last {days} days")
            except Exception as e:
                logger.error(f"ChromaDB cleanup error: {e}")

        # Архивируем старые факты (устанавливаем valid_to)
        conn = sqlite3.connect(self.graph_db)
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE facts
        SET valid_to = ?, updated_at = ?
        WHERE created_at < ? AND valid_to IS NULL
        """, (datetime.now().isoformat(), datetime.now().isoformat(),
              datetime.fromtimestamp(cutoff_date).isoformat()))

        archived = cursor.rowcount

        conn.commit()
        conn.close()
        logger.info(f"Cleanup complete: archived {archived} old facts")