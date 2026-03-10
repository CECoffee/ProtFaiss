import sys
import re
import psycopg2
from psycopg2.extras import execute_values

# --- 1. 数据库配置 ---
# [!] 请在此处修改您的数据库连接信息
DB_CONFIG = {
    "host": "localhost",       # 数据库服务器地址 (e.g., 'localhost' or '127.0.0.1')
    "port": 5432,              # 默认端口
    "dbname": "protein_db",    # 您的数据库名称
    "user": "postgres",        # 您的用户名
    "password": "0909" # 您的密码
}

# --- 2. 批量插入设置 ---
BATCH_SIZE = 1000 # 每次向数据库提交 1000 条记录

# --- 3. FASTA Header 解析函数 (来自我们之前的讨论) ---
def parse_fasta_header(header_string):
    """
    使用正则表达式解析 FASTA header。
    e.g., "blk_pm_opera_..._KO:K00001_EC:1.1.1.1"
    """
    
    # 默认值
    accession = header_string
    ko = None
    ec = None

    # 1. 尝试提取 KO
    # 匹配 KO:K followed by 5 digits
    ko_match = re.search(r'KO:(K\d{5})', header_string)
    if ko_match:
        ko = ko_match.group(1) # e.g., "K00001"
        
    # 2. 尝试提取 EC
    # 匹配 EC: followed by digits, dots, or 'n' or '-' (e.g., 1.1.1.1 or 1.14.n.-)
    ec_match = re.search(r'EC:([\d\.\-n]+)', header_string)
    if ec_match:
        ec = ec_match.group(1) # e.g., "1.1.1.1"

    # 3. 提取 Accession (KO 或 EC 之前的所有内容)
    # 找到第一个 _KO: 或 _EC: 出现的位置
    split_pos = -1
    ko_pos = header_string.find('_KO:')
    ec_pos = header_string.find('_EC:')

    if ko_pos != -1 and ec_pos != -1:
        split_pos = min(ko_pos, ec_pos)
    elif ko_pos != -1:
        split_pos = ko_pos
    elif ec_pos != -1:
        split_pos = ec_pos
        
    if split_pos != -1:
        accession = header_string[:split_pos]
    
    return accession, ko, ec

# --- 4. FASTA 文件迭代器 (get_data_iterator) ---
def fasta_data_iterator(fasta_file_path):
    """
    一个用于 FASTA 文件的迭代器 (生成器)。
    逐条读取记录，不将整个文件加载到内存。
    Yields: (original_header, accession, ko, ec, sequence, seq_len, ph_val)
    """
    print(f"开始处理文件: {fasta_file_path}")
    header = None
    sequence_parts = []
    
    try:
        with open(fasta_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue # 跳过空行
                
                if line.startswith('>'):
                    # 当遇到新的 header 时，处理并 yield 上一条记录
                    if header:
                        full_sequence = "".join(sequence_parts)
                        original_header = header.lstrip('>') # 移除 '>'
                        
                        # 解析
                        accession, ko, ec = parse_fasta_header(original_header)
                        seq_len = len(full_sequence)
                        ph_val = None # [关键] FASTA 文件没有 pH 值, 设为 None
                        
                        yield (original_header, accession, ko, ec, full_sequence, seq_len, ph_val)
                    
                    # 开始一条新记录
                    header = line
                    sequence_parts = []
                else:
                    # 这是序列行
                    sequence_parts.append(line)
            
            # 循环结束后，不要忘记 yield 最后一条记录
            if header:
                full_sequence = "".join(sequence_parts)
                original_header = header.lstrip('>')
                accession, ko, ec = parse_fasta_header(original_header)
                seq_len = len(full_sequence)
                ph_val = None
                
                yield (original_header, accession, ko, ec, full_sequence, seq_len, ph_val)

    except FileNotFoundError:
        print(f"错误: 文件 {fasta_file_path} 未找到。", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"读取文件时出错: {e}", file=sys.stderr)
        sys.exit(1)


# --- 5. 主执行函数 ---
def main(fasta_file):
    """
    主函数，连接数据库并批量插入数据。
    """
    
    # [关键]：此 ID 必须从 0 开始，以匹配 FAISS 索引
    current_id = 0
    data_batch = []
    
    # SQL 插入语句
    # 注意列的顺序必须与 data_batch 中元组的顺序完全一致
    insert_query = """
    INSERT INTO proteins (
        id, original_header, accession, ko_number, ec_number, 
        sequence, sequence_length, ph_processed
    ) VALUES %s
    """
    
    try:
        # 连接数据库
        print(f"正在连接到数据库 {DB_CONFIG['dbname']}...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("连接成功。")
        
        # 迭代 FASTA 文件
        for record in fasta_data_iterator(fasta_file):
            (original_header, accession, ko, ec, sequence, seq_len, ph_val) = record
            
            # [关键]：将我们生成的 ID (current_id) 添加到记录中
            db_id = current_id
            data_batch.append(
                (db_id, original_header, accession, ko, ec, sequence, seq_len, ph_val)
            )
            
            current_id += 1
            
            # 当批次达到大小时，执行插入
            if len(data_batch) >= BATCH_SIZE:
                execute_values(cursor, insert_query, data_batch)
                conn.commit()
                print(f"已插入 {current_id} 条记录...")
                data_batch = [] # 清空批次
        
        # 插入剩余的最后批次
        if data_batch:
            execute_values(cursor, insert_query, data_batch)
            conn.commit()
            print(f"已插入最后批次，总计 {current_id} 条记录。")
            
        print("数据插入完成。")

    except psycopg2.Error as e:
        print(f"数据库错误: {e}", file=sys.stderr)
        conn.rollback() # 回滚事务
    except Exception as e:
        print(f"发生意外错误: {e}", file=sys.stderr)
    finally:
        # 确保关闭连接
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()
            print("数据库连接已关闭。")

# --- 脚本入口 ---
if __name__ == "__main__":
    fasta_file_path = "../src/KEGG_test.fasta"  # [!] 要处理的文件名
    main(fasta_file_path)