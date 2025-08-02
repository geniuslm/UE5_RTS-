#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计算项目中所有MD文件的总字数（以汉字为准）
"""

import os
import re
from pathlib import Path

def count_chinese_chars(text):
    """统计文本中的汉字数量"""
    # 匹配汉字的正则表达式
    chinese_pattern = r'[\u4e00-\u9fff]+'
    chinese_chars = re.findall(chinese_pattern, text)
    return sum(len(chars) for chars in chinese_chars)

def count_md_files_words(directory):
    """统计目录下所有MD文件的汉字总数"""
    total_chars = 0
    file_count = 0
    
    directory_path = Path(directory)
    
    print("UE5 RTS项目 MD文件汉字统计")
    print("=" * 50)
    print(f"正在扫描目录: {directory_path.absolute()}")
    print("-" * 50)
    
    # 遍历所有.md文件
    for md_file in directory_path.rglob("*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                char_count = count_chinese_chars(content)
                total_chars += char_count
                file_count += 1
                
                # 显示每个文件的字数
                relative_path = md_file.relative_to(directory_path)
                print(f"{relative_path}: {char_count:,} 汉字")
                
        except Exception as e:
            print(f"读取文件 {md_file} 时出错: {e}")
    
    print("-" * 50)
    print(f"总计: {file_count} 个MD文件")
    print(f"总汉字数: {total_chars:,} 字")
    
    if total_chars > 10000:
        print(f"项目规模: {total_chars/10000:.1f} 万字")
    
    return total_chars, file_count

if __name__ == "__main__":
    # 获取当前脚本所在目录作为项目根目录
    project_root = os.path.dirname(os.path.abspath(__file__))
    count_md_files_words(project_root)