import os
import yaml


class BuilderPromptYaml:
    """把 YAML 提示词拼成一段文本。
    """

    @staticmethod
    def get_prompt(file_name: str) -> str:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_dir, file_name)

        with open(file_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        if not config.get('role'):
            raise ValueError(f'{file_name} 缺少 role（角色）字段')

        def lines(key: str) -> list[str]:
            """取一节内容并规整成字符串列表：支持列表，也容忍写成单个字符串。"""
            value = config.get(key)
            if not value:
                return []
            if isinstance(value, str):
                return [value]
            return [str(item) for item in value]

        sections = [
            ('一 角色:', [config['role']]),
            ('二 任务:', lines('task')),
            ('三 规则:', lines('rule')),
            ('四 输出:', lines('output')),
            ('五 示例:', lines('example')),
            ('六 输入数据:', lines('input')),
        ]

        prompt = '\n'.join(
            f'{title}\n' + '\n'.join(body)
            for title, body in sections
            if body
        )
        return prompt.strip()


if __name__ == '__main__':
    b = BuilderPromptYaml()
    print(b.get_prompt('intent_search_node.yaml')[:200])
