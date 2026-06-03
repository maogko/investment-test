"""スクリーニング対象の銘柄ユニバース（既定値）。

初心者でも名前を聞いたことがある、長期保有に向きやすい大型・優良銘柄を
セクター横断で集めた既定リスト。`--tickers` で自由に差し替え可能。

注意: このリストは「分析の出発点」であり、推奨銘柄ではありません。
実際に推奨されるかどうかは最新データに基づくスコアリングで決まります。
"""

# ティッカー一覧（Yahoo Finance 形式）。
# 日本株は "7203.T" のように末尾に .T を付けると取得できます。
DEFAULT_UNIVERSE = [
    # 米国・大型テック / 半導体
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Alphabet
    "AMZN",   # Amazon
    "META",   # Meta Platforms
    "NVDA",   # NVIDIA
    "AVGO",   # Broadcom
    # 生活必需品 / ヘルスケア（ディフェンシブ）
    "JNJ",    # Johnson & Johnson
    "PG",     # Procter & Gamble
    "KO",     # Coca-Cola
    "PEP",    # PepsiCo
    "UNH",    # UnitedHealth
    "COST",   # Costco
    # 金融 / 決済
    "V",      # Visa
    "MA",     # Mastercard
    "JPM",    # JPMorgan Chase
    "BRK-B",  # Berkshire Hathaway
    # 資本財 / 一般消費
    "HD",     # Home Depot
    "MCD",    # McDonald's
    # エネルギー
    "XOM",    # Exxon Mobil
]
