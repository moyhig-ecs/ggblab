declare global {
  interface Window {
    GGBApplet: any; // GGBAppletをany型として宣言
    // 他にもグローバルに公開される関数があればここに追加
  }
}
export {}; // モジュールとして機能させるための空のエクスポート