-- ============================================================================
-- FreeData.AI | Test de fumée du RAG (sql/05_rag_documents.sql)
--
-- Tout s'exécute dans UNE transaction qui se termine par ROLLBACK : aucune donnée de test
-- ne subsiste, même si tout réussit. À lancer dans l'éditeur SQL après sql/05.
-- Lis les messages "NOTICE" : chaque contrôle affiche OK ou lève une erreur.
-- ============================================================================

BEGIN;

-- Données factices : un document public, un document NON redistribuable, un extrait chacun.
-- Les vecteurs sont des constantes (dimension 1024) ; seul le premier composant les distingue.
INSERT INTO public.rag_documents (id, title, publisher, redistribution_ok)
OVERRIDING SYSTEM VALUE
VALUES (900001, 'Document de test public', 'TEST', TRUE),
       (900002, 'Document de test PRIVÉ',  'TEST', FALSE);

INSERT INTO public.rag_chunks (document_id, chunk_index, page, content, content_hash, embedding)
VALUES (900001, 0, 1, 'extrait public', 'h1', (ARRAY[1.0] || array_fill(0.0::real, ARRAY[1023]))::extensions.vector),
       (900002, 0, 1, 'extrait privé',  'h2', (ARRAY[1.0] || array_fill(0.0::real, ARRAY[1023]))::extensions.vector);

-- Contrôle 1 : la recherche renvoie l'extrait public et JAMAIS l'extrait du document privé.
DO $$
DECLARE n INTEGER; premier TEXT;
BEGIN
    SELECT COUNT(*), MIN(content) INTO n, premier
    FROM public.match_chunks((ARRAY[1.0] || array_fill(0.0::real, ARRAY[1023]))::extensions.vector, 5);
    IF n = 1 AND premier = 'extrait public' THEN
        RAISE NOTICE 'OK 1 : seul l''extrait redistribuable est renvoyé';
    ELSE
        RAISE EXCEPTION 'ÉCHEC 1 : % ligne(s), premier = %', n, premier;
    END IF;
END $$;

-- Contrôle 2 : le plafond de 10 résultats tient, même si on en demande 1000.
DO $$
DECLARE n INTEGER;
BEGIN
    SELECT COUNT(*) INTO n
    FROM public.match_chunks((ARRAY[1.0] || array_fill(0.0::real, ARRAY[1023]))::extensions.vector, 1000);
    IF n <= 10 THEN RAISE NOTICE 'OK 2 : plafond respecté (% ligne)', n;
    ELSE RAISE EXCEPTION 'ÉCHEC 2 : % lignes renvoyées', n; END IF;
END $$;

-- Contrôle 3 : en tant qu'anon, la lecture marche mais ne voit pas le document privé.
DO $$
DECLARE n_docs INTEGER; n_chunks INTEGER;
BEGIN
    SET LOCAL ROLE anon;
    SELECT COUNT(*) INTO n_docs FROM public.rag_documents;
    SELECT COUNT(*) INTO n_chunks FROM public.rag_chunks;
    RESET ROLE;
    IF n_docs = 1 AND n_chunks = 1 THEN
        RAISE NOTICE 'OK 3 : anon lit uniquement le contenu redistribuable';
    ELSE
        RAISE EXCEPTION 'ÉCHEC 3 : anon voit % document(s) et % extrait(s)', n_docs, n_chunks;
    END IF;
END $$;

-- Contrôle 4 : en tant qu'anon, aucune écriture n'est possible (INSERT, UPDATE, DELETE).
DO $$
DECLARE refus INTEGER := 0;
BEGIN
    BEGIN
        SET LOCAL ROLE anon;
        INSERT INTO public.rag_documents (title, publisher) VALUES ('intrus', 'X');
        RESET ROLE;
    EXCEPTION WHEN insufficient_privilege THEN refus := refus + 1; RESET ROLE;
    END;
    BEGIN
        SET LOCAL ROLE anon;
        UPDATE public.rag_documents SET redistribution_ok = TRUE;
        RESET ROLE;
    EXCEPTION WHEN insufficient_privilege THEN refus := refus + 1; RESET ROLE;
    END;
    BEGIN
        SET LOCAL ROLE anon;
        DELETE FROM public.rag_chunks;
        RESET ROLE;
    EXCEPTION WHEN insufficient_privilege THEN refus := refus + 1; RESET ROLE;
    END;
    IF refus = 3 THEN RAISE NOTICE 'OK 4 : INSERT, UPDATE et DELETE refusés pour anon';
    ELSE RAISE EXCEPTION 'ÉCHEC 4 : seulement % écriture(s) sur 3 refusée(s)', refus; END IF;
END $$;

-- Contrôle 5 : aucun extrait ne subsiste après le test (état vide = état de production actuel).
ROLLBACK;

SELECT COUNT(*) AS extraits_restants FROM public.rag_chunks;  -- doit afficher 0
