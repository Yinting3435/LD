from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
from datetime import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
from urllib.parse import urlparse
import sys

app = Flask(__name__)

# 配置Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'demo'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', 'demo'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'demo')
)

# 数据库连接与表初始化函数（核心修复）
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    print(f"[DEBUG] DATABASE_URL 存在: {bool(database_url)}", file=sys.stderr)

    # 在Vercel环境中，必须使用PostgreSQL
    if database_url and database_url.startswith('postgres'):
        # 修复URL格式
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        try:
            import psycopg2
            print("[DEBUG] 尝试连接 PostgreSQL...", file=sys.stderr)
            conn = psycopg2.connect(database_url, sslmode='require')
            
            # 关键：连接成功后，立即检查并创建表
            init_table(conn)
            
            return conn
        except ImportError:
            print("[ERROR] 缺少 psycopg2 库。请在 requirements.txt 中添加 psycopg2-binary。", file=sys.stderr)
            raise
        except Exception as e:
            print(f"[ERROR] PostgreSQL 连接失败: {e}", file=sys.stderr)
            raise Exception(f"无法连接到 PostgreSQL 数据库: {e}")
    else:
        # 本地开发回退到 SQLite
        if os.environ.get('VERCEL'):
            raise Exception("在 Vercel 环境中必须配置有效的 DATABASE_URL 环境变量。")
        
        import sqlite3
        print("[DEBUG] 本地开发：使用 SQLite 数据库", file=sys.stderr)
        conn = sqlite3.connect('love_diary.db')
        init_table(conn)  # 本地也初始化表
        return conn

def init_table(connection):
    """初始化数据库表，如果不存在则创建。"""
    cursor = connection.cursor()
    try:
        # 兼容 PostgreSQL 和 SQLite 的建表语句
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS diary (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            img_url TEXT,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        cursor.execute(create_table_sql)
        connection.commit()
        print("[DEBUG] 已确认 diary 表存在。", file=sys.stderr)
    except Exception as e:
        # 如果上面的语法失败，尝试 SQLite 语法
        try:
            create_table_sql_sqlite = """
            CREATE TABLE IF NOT EXISTS diary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                img_url TEXT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            cursor.execute(create_table_sql_sqlite)
            connection.commit()
            print("[DEBUG] 已使用 SQLite 语法确认 diary 表存在。", file=sys.stderr)
        except Exception as e2:
            print(f"[ERROR] 创建 diary 表失败: {e2}", file=sys.stderr)
            connection.rollback()
            raise
    finally:
        cursor.close()

# 计算恋爱天数
def calculate_love_days():
    start_date = datetime(2026, 4, 5)  # 恋爱开始日期
    today = datetime.now()
    start_date = datetime(start_date.year, start_date.month, start_date.day)
    today = datetime(today.year, today.month, today.day)
    time_diff = today - start_date
    return max(0, time_diff.days)

# 首页
@app.route('/', methods=['GET', 'POST'])
def index():
    love_days = calculate_love_days()
    
    if request.method == 'POST' and 'content' in request.form:
        content = request.form['content']
        img = request.files.get('img')
        img_url = None
        
        if img and img.filename:
            try:
                upload_result = cloudinary.uploader.upload(img)
                img_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"[ERROR] 图片上传失败: {e}", file=sys.stderr)
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO diary (content, img_url) VALUES (%s, %s)', (content, img_url))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            return f"保存日记时出错: {e}", 500

    # 读取所有日记
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, content, img_url, create_time FROM diary ORDER BY create_time DESC')
        diaries = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"[ERROR] 读取日记失败: {e}", file=sys.stderr)
        diaries = []

    return render_template('index.html', diaries=diaries, love_days=love_days)

# 删除日记
@app.route('/delete/<int:diary_id>', methods=['POST'])
def delete_diary(diary_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT img_url FROM diary WHERE id = %s', (diary_id,))
        result = cursor.fetchone()
        
        if result:
            img_url = result[0]
            if img_url and 'cloudinary.com' in img_url:
                try:
                    public_id = img_url.split('/')[-1].split('.')[0]
                    cloudinary.uploader.destroy(public_id)
                except Exception as e:
                    print(f"[ERROR] 删除 Cloudinary 图片失败: {e}", file=sys.stderr)
            
            cursor.execute('DELETE FROM diary WHERE id = %s', (diary_id,))
            conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': '日记删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# 健康检查
@app.route('/health')
def health():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.fetchone()
        conn.close()
        return 'OK - 数据库连接正常'
    except Exception as e:
        return f'ERROR - 数据库连接失败: {e}', 500

# 环境检查
@app.route('/env-check')
def env_check():
    env_info = {
        'DATABASE_URL_exists': bool(os.environ.get('DATABASE_URL')),
        'CLOUDINARY_CLOUD_NAME_exists': bool(os.environ.get('CLOUDINARY_CLOUD_NAME')),
        'VERCEL_env': bool(os.environ.get('VERCEL')),
    }
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        # 只显示前后部分，隐藏中间敏感信息
        env_info['DATABASE_URL_preview'] = db_url[:20] + '...' + db_url[-20:] if len(db_url) > 40 else db_url
    return jsonify(env_info)

# 安全的管理员初始化路由（备用）
@app.route('/admin/init-table/<secret_key>')
def admin_init_table(secret_key):
    # 请务必在Vercel环境变量中设置一个复杂的 ADMIN_SECRET_KEY
    if secret_key != os.environ.get('ADMIN_SECRET_KEY', 'default_insecure_key'):
        return 'Unauthorized', 403
    try:
        conn = get_db_connection()  # 连接时会自动初始化表
        conn.close()
        return '✅ 数据库表初始化完成（或已存在）。'
    except Exception as e:
        return f'❌ 初始化失败: {e}', 500

if __name__ == '__main__':
    # 本地运行时，也确保表存在
    try:
        conn = get_db_connection()
        conn.close()
    except Exception as e:
        print(f"[WARNING] 本地数据库初始化时出现警告: {e}")
    app.run(host='0.0.0.0', port=8080, debug=True)
