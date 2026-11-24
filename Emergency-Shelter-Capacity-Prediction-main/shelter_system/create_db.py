import pymysql

conn = pymysql.connect(host='localhost', user='root', password='1233')
cursor = conn.cursor()
cursor.execute('CREATE DATABASE IF NOT EXISTS shelter_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
cursor.execute('SHOW DATABASES')
dbs = [row[0] for row in cursor.fetchall()]
conn.close()

if 'shelter_system' in dbs:
    print('SUCCESS: shelter_system database exists.')
else:
    print('ERROR: database was not created.')
