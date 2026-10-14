# 按应用自动切换模式

焦点切到某个应用时，OmniPal 会自动换成你给它指定的模式，切到没有规则的应用时，再回到基准模式。

## 三步上手

```bash
# 1. 切到 VS Code，然后运行（自动取当前窗口的类名）
omni-profile rules add --current mac
# 或者手动写类名
omni-profile rules add code mac
# 2. 查看规则
omni-profile rules list
# 3. 试一下某个类名会命中哪条
omni-profile rules test code
```

也可以在设置中心（Super+,）的“🧩 应用规则”页里点“填入当前应用”来添加。

## 规则怎么匹配

- 每条规则包含窗口类名、匹配方式、目标模式和启用开关。
- 匹配方式有三种：精确、前缀、正则，都不区分大小写。
- 按顺序检查，第一条命中的规则生效。
- 规则保存在 `~/.config/omnipal/app_rules.json`，添加第一条规则时才会创建。保存时会校验，模式不存在或正则写错都会被拒绝。

## 基准模式

没有规则命中时用的就是基准模式。默认是你最后一次手动选的模式，也可以用 `omni-profile rules default <模式>` 固定成某一个。
规则生效期间你手动换了模式，这个模式会成为新的基准，离开那个应用后也不会被改回去。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `rules add <类名> <模式>` | 添加规则 |
| `rules add --current <模式>` | 用当前焦点窗口添加 |
| `rules remove <类名>` | 删除规则 |
| `rules enable/disable <类名>` | 启用或停用某条规则 |
| `rules default <模式>` | 固定基准模式 |
| `rules test <类名>` | 查看会命中哪条规则 |
