import mysql.connector
from mysql.connector import Error

# 数据库连接配置
db_config = {
    'host': 'localhost',
    'user': 'your_username',
    'password': 'your_password',
    'database': 'your_database'
}

# 创建数据库连接
def create_connection():
    connection = None
    try:
        connection = mysql.connector.connect(**db_config)
        print("MySQL数据库连接成功")
    except Error as e:
        print(f"连接MySQL数据库时出错: {e}")
    return connection

# 创建表
def create_table(connection, create_table_sql):
    try:
        cursor = connection.cursor()
        cursor.execute(create_table_sql)
        print("表创建成功")
    except Error as e:
        print(f"创建表时出错: {e}")

# 插入数据
def insert_data(connection, insert_sql, data):
    try:
        cursor = connection.cursor()
        cursor.execute(insert_sql, data)
        connection.commit()
        print(f"插入数据成功，ID: {cursor.lastrowid}")
    except Error as e:
        print(f"插入数据时出错: {e}")

# 查询数据
def query_data(connection, query_sql, params=None):
    try:
        cursor = connection.cursor(dictionary=True)
        if params:
            cursor.execute(query_sql, params)
        else:
            cursor.execute(query_sql)
        
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"查询数据时出错: {e}")
        return None

# 更新数据
def update_data(connection, update_sql, data):
    try:
        cursor = connection.cursor()
        cursor.execute(update_sql, data)
        connection.commit()
        print(f"更新数据成功，影响行数: {cursor.rowcount}")
    except Error as e:
        print(f"更新数据时出错: {e}")

# 删除数据
def delete_data(connection, delete_sql, data):
    try:
        cursor = connection.cursor()
        cursor.execute(delete_sql, data)
        connection.commit()
        print(f"删除数据成功，影响行数: {cursor.rowcount}")
    except Error as e:
        print(f"删除数据时出错: {e}")

# 使用示例
if __name__ == "__main__":
    # 创建连接
    conn = create_connection()
    
    if conn is not None:
        # 创建表SQL
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        
        # 创建表
        create_table(conn, create_table_sql)
        
        # 插入数据
        insert_sql = "INSERT INTO users (name, email) VALUES (%s, %s)"
        user_data = ("张三", "zhangsan@example.com")
        insert_data(conn, insert_sql, user_data)
        
        # 查询数据
        query_sql = "SELECT * FROM users WHERE name = %s"
        users = query_data(conn, query_sql, ("张三",))
        print("查询结果:", users)
        
        # 更新数据
        update_sql = "UPDATE users SET email = %s WHERE name = %s"
        update_data(conn, update_sql, ("new_email@example.com", "张三"))
        
        # 再次查询验证更新
        users = query_data(conn, query_sql, ("张三",))
        print("更新后查询结果:", users)
        
        # 删除数据
        delete_sql = "DELETE FROM users WHERE name = %s"
        delete_data(conn, delete_sql, ("张三",))
        
        # 关闭连接
        conn.close()
        print("数据库连接已关闭")
    else:
        print("无法连接到数据库")