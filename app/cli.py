"""`flask <명령>` 으로 실행하는 관리 명령.

  flask seed-demo        로그인용 데모 계정 생성
"""
import click


def register_cli(app):
    @app.cli.command("seed-demo")
    def seed_demo_cmd():
        from scripts.seed_demo import seed
        click.echo(seed())
