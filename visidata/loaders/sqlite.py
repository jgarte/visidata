from visidata import *


class SqliteSheet(Sheet):
    'Provide functionality for importing SQLite databases.'
    savesToSource = True
    defermods = True

    def resolve(self):
        'Resolve all the way back to the original source Path.'
        return self.source.resolve()

    def conn(self):
        import sqlite3
        return sqlite3.connect(str(self.resolve()))

    def execute(self, conn, sql, where={}, parms=None):
        parms = parms or []
        if where:
            sql += ' WHERE %s' % ' AND '.join('"%s"=?' % k for k in where)
        status(sql)
        parms += list(where.values())
        return conn.execute(sql, parms)

    def iterload(self):
        sqltypes = {
            'INTEGER': int,
            'TEXT': anytype,
            'BLOB': str,
            'REAL': float
        }

        with self.conn() as conn:
            tblname = self.tableName
            if not isinstance(self, SqliteIndexSheet):
                self.columns = []
                for i, r in enumerate(self.execute(conn, 'PRAGMA TABLE_INFO("%s")' % tblname)):
                    c = ColumnItem(r[1], i, type=sqltypes.get(r[2].upper(), anytype))
                    self.addColumn(c)

                    if r[-1]:
                        self.setKeys([c])

            r = self.execute(conn, 'SELECT COUNT(*) FROM "%s"' % tblname).fetchall()
            rowcount = r[0][0]
            for row in Progress(self.execute(conn, 'SELECT * FROM "%s"' % tblname), total=rowcount-1):
                yield row

    @asyncthread
    def putChanges(self, path, adds, mods, dels):
        options_safe_error = options.safe_error
        def value(row, col):
            v = col.getTypedValue(row)
            if isinstance(v, TypedWrapper):
                if isinstance(v, TypedExceptionWrapper):
                    return options_safe_error
                else:
                    return None
            return v

        def values(row, cols):
            vals = []
            for c in cols:
                vals.append(value(row, c))
            return vals

        with self.conn() as conn:
            wherecols = self.keyCols or self.visibleCols
            for r in adds.values():
                cols = self.visibleCols
                sql = 'INSERT INTO "%s" ' % self.tableName
                sql += '(%s)' % ','.join(c.name for c in cols)
                sql += 'VALUES (%s)' % ','.join('?' for c in cols)
                self.execute(conn, sql, parms=values(r, cols))

            for row, rowmods in mods.values():
                sql = 'UPDATE "%s" SET ' % self.tableName
                sql += ', '.join('%s=?' % c.name for c, _ in rowmods.items())
                self.execute(conn, sql,
                            where={c.name: c.getSavedValue(row) for c in wherecols},
                            parms=values(row, [c for c, _ in rowmods.items()]))

            for r in dels.values():
                self.execute(conn, 'DELETE FROM "%s" ' % self.tableName,
                              where={c.name: c.getTypedValue(r) for c in wherecols})

            conn.commit()

        self.reload()
        self._dm_reset()


class SqliteIndexSheet(SqliteSheet, IndexSheet):
    tableName = 'sqlite_master'
    def iterload(self):
        for row in SqliteSheet.iterload(self):
            if row[0] != 'index':
                tblname = row[1]
                yield SqliteSheet(tblname, source=self, tableName=tblname, row=row)


@asyncthread
def multisave_sqlite(p, *vsheets):
    import sqlite3
    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    sqltypes = {
        int: 'INTEGER',
        float: 'REAL',
        currency: 'REAL'
    }

    for vs in vsheets:
        tblname = clean_to_id(vs.name)
        sqlcols = []
        for col in vs.visibleCols:
            sqlcols.append('"%s" %s' % (col.name, sqltypes.get(col.type, 'TEXT')))
        sql = 'CREATE TABLE IF NOT EXISTS "%s" (%s)' % (tblname, ', '.join(sqlcols))
        c.execute(sql)

        for r in Progress(vs.rows, 'saving'):
            sqlvals = []
            for col in vs.visibleCols:
                sqlvals.append(col.getTypedValue(r))
            sql = 'INSERT INTO "%s" VALUES (%s)' % (tblname, ','.join('?' for v in sqlvals))
            c.execute(sql, sqlvals)

    conn.commit()

    status("%s save finished" % p)


options.set('header', 0, SqliteSheet)
save_db = save_sqlite = multisave_db = multisave_sqlite

vd.filetype('sqlite', SqliteIndexSheet)
vd.filetype('sqlite3', SqliteIndexSheet)
vd.filetype('db', SqliteIndexSheet)
