from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
from datetime import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
from urllib.parse import urlparse
import os.path

app = Flask(__name__)

# 配置Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'demo'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', 'demo'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'demo')
)

# 数据库连接函数 - 同时支持SQLite和PostgreSQL
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    
    # 本地开发：如果没有设置DATABASE_URL，使用SQLite
    if not database_url or database_url.startswith('sqlite'):
        import sqlite3
        # 本地开发使用SQLite
        conn = sqlite3.connect('love_diary.db')
        return conn
    
    # 生产环境：使用PostgreSQL
    # 修复URL格式（Vercel Postgres使用postgres://，但psycopg2需要postgresql://）
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # 连接到PostgreSQL
        conn = psycopg2.connect(
            database_url,
            sslmode='require'
        )
        return conn
    except ImportError:
        # 如果psycopg2没有安装，在本地回退到SQLite
        import sqlite3
        conn = sqlite3.connect('love_diary.db')
        return conn
    except Exception as e:
        print(f"数据库连接错误: {e}")
        # 如果PostgreSQL连接失败，在本地回退到SQLite
        import sqlite3
        conn = sqlite3.connect('love_diary.db')
        return conn

# 初始化数据库
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 尝试PostgreSQL语法
    try:
        c.execute('''
            CREATE TABLE IF NOT EXISTS diary (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                img_url TEXT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except:
        # 如果失败，尝试SQLite语法
        try:
            c.execute('''
                CREATE TABLE IF NOT EXISTS diary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    img_url TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        except Exception as e:
            print(f"创建表失败: {e}")
    
    conn.commit()
    conn.close()

# 计算恋爱天数
def calculate_love_days():
    start_date = datetime(2026, 4, 5)  # 恋爱开始日期
    today = datetime.now()
    # 清除时间部分，只比较日期
    start_date = datetime(start_date.year, start_date.month, start_date.day)
    today = datetime(today.year, today.month, today.day)
    
    # 计算天数差
    time_diff = today - start_date
    return max(0, time_diff.days)  # 确保不会显示负数

# 首页
@app.route('/', methods=['GET', 'POST'])
def index():
    # 计算恋爱天数
    love_days = calculate_love_days()
    
    # 保存日记
    if request.method == 'POST' and 'content' in request.form:
        content = request.form['content']
        img = request.files.get('img')
        img_url = None
        
        if img and img.filename:
            try:
                # 上传图片到Cloudinary
                upload_result = cloudinary.uploader.upload(img)
                img_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"图片上传失败: {e}")
                img_url = None
        
        conn = get_db_connection()
        c = conn.cursor()
        
        # 插入数据 - 使用参数化查询
        try:
            c.execute('INSERT INTO diary (content, img_url) VALUES (%s, %s)', 
                     (content, img_url))
        except:
            # 如果上面的语句失败，使用SQLite的参数格式
            c.execute('INSERT INTO diary (content, img_url) VALUES (?, ?)', 
                     (content, img_url))
        
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    # 读取所有日记
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        c.execute('SELECT id, content, img_url, create_time FROM diary ORDER BY create_time DESC')
    except:
        # 如果失败，可能是SQLite语法问题
        c.execute('SELECT id, content, img_url, create_time FROM diary ORDER BY create_time DESC')
    
    diaries = c.fetchall()
    conn.close()

    return render_template('index.html', diaries=diaries, love_days=love_days)

# 删除日记的路由
@app.route('/delete/<int:diary_id>', methods=['POST'])
def delete_diary(diary_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # 首先获取日记信息，包括图片URL
        try:
            c.execute('SELECT img_url FROM diary WHERE id = %s', (diary_id,))
        except:
            c.execute('SELECT img_url FROM diary WHERE id = ?', (diary_id,))
        
        result = c.fetchone()
        
        if result:
            img_url = result[0]
            # 如果有图片，从Cloudinary删除
            if img_url and 'cloudinary.com' in img_url:
                try:
                    # 从URL中提取public_id
                    public_id = img_url.split('/')[-1].split('.')[0]
                    cloudinary.uploader.destroy(public_id)
                except Exception as e:
                    print(f"删除Cloudinary图片失败: {e}")
            
            # 从数据库中删除日记
            try:
                c.execute('DELETE FROM diary WHERE id = %s', (diary_id,))
            except:
                c.execute('DELETE FROM diary WHERE id = ?', (diary_id,))
            
            conn.commit()
            
        conn.close()
        return jsonify({'success': True, 'message': '日记删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# API端点：获取恋爱天数
@app.route('/api/love_days')
def api_love_days():
    return jsonify({'love_days': calculate_love_days()})

# 健康检查
@app.route('/health')
def health():
    return 'OK'

# 数据库状态检查
@app.route('/db-status')
def db_status():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT 1')
        result = c.fetchone()
        conn.close()
        return jsonify({
            'status': 'connected',
            'database_type': 'PostgreSQL' if os.environ.get('DATABASE_URL') else 'SQLite'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    init_db()
    # 本地+手机都能访问
    app.run(host='0.0.0.0', port=8080, debug=True)
