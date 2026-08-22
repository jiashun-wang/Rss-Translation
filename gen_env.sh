#!/usr/bin/env bash
# 一键扫描所有 .py 中的环境变量并生成 .env 模板
OUT=".env"
echo "# 由 gen_env.sh 自动扫描生成的 .env 模板（请填写真实值）" > "$OUT"
echo "# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$OUT"

grep -rhoE 'os\.environ\.(get|getenv)\("[^"]+"[^)]*\)' --include="*.py" . 2>/dev/null | sort -u | while read -r line; do
    # 提取变量名（第一个引号内的内容）
    key=$(echo "$line" | sed -E 's/.*\( *"([^"]+)".*/\1/')
    # 提取默认值（第二个引号内的内容，若有）
    default=$(echo "$line" | sed -nE 's/.*, *"([^"]*)"[^)]*\).*/\1/p')
    if [ -n "$default" ]; then
        echo "$key=$default" >> "$OUT"
    else
        echo "$key=" >> "$OUT"
    fi
done

echo "" >> "$OUT"
echo "# 以下为项目其他常见配置说明：" >> "$OUT"
echo "# DEEPSEEK_API_KEY=sk-在这里填入你的密钥" >> "$OUT"

echo "✅ 已生成 $OUT 文件，内容如下："
cat "$OUT"

# 顺便更新 .gitignore，防止 .env 泄露
if [ -f ".gitignore" ] && ! grep -q "^\.env" ".gitignore"; then
    echo ".env" >> .gitignore
    echo "✅ 已将 .env 加入 .gitignore"
elif [ ! -f ".gitignore" ]; then
    echo ".env" > .gitignore
    echo "✅ 已创建 .gitignore 并包含 .env"
fi
