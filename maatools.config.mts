import type { FullConfig } from '@nekosu/maa-tools'

const config: FullConfig = {
  cwd: import.meta.dirname,
  // 与 .github/workflows/install.yml 的 MAAFW_VERSION 保持一致：
  // 校验按「实际发布的那版框架」做，而不是 latest，否则 check 会按更新的框架
  // 报出你还没升级的字段/行为。
  maaVersion: 'v5.14.3',
  interfacePath: 'assets/interface.json',
  check: {
    override: {
      // 忽略 mpe-config 带来的报错
      // ignore warning caused by mpe-config
      // 'mpe-config': 'ignore'
    }
  }
}

export default config
