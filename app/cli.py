"""Command Line Interface for system management tasks.

This module provides CLI commands to manage admin users and other system
tasks using Typer.
"""

import typer
from email_validator import EmailNotValidError, validate_email

from app.core.security import security_service
from app.db.session import SessionLocal, get_engine
from app.modules.auth.constants import UserRole
from app.modules.auth.models import User

app_cli = typer.Typer(help="FluentMeet management commands.")


@app_cli.command()
def create_admin(
    email: str = typer.Option(
        None,
        "--email",
        "-e",
        help="Email address for the new admin user.",
    ),
    password: str = typer.Option(
        None,
        "--password",
        "-p",
        help="Password for the new admin user. (Insecure if passed via shell history)",
    ),
    full_name: str = typer.Option(
        "System Admin",
        "--full-name",
        "-n",
        help="Full name of the new admin user.",
    ),
    no_input: bool = typer.Option(
        False,
        "--no-input",
        help="Non-interactive mode (no prompts, fails if credentials not supplied).",
    ),
) -> None:
    """Create a new admin user."""
    # Handle credentials input based on mode
    if no_input:
        if not email or not password:
            typer.echo(
                "Error: Both --email and --password must be provided in "
                "non-interactive mode.",
                err=True,
            )
            raise typer.Exit(code=1)
    else:
        if not email:
            email = typer.prompt("Admin email address")
        if not password:
            password = typer.prompt(
                "Admin password",
                hide_input=True,
                confirmation_prompt=True,
            )

    # Validate email format
    try:
        validation = validate_email(email, check_deliverability=False)
        email = validation.normalized
    except EmailNotValidError as exc:
        typer.echo(f"Error: Invalid email address: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Ensure engine is bound and open session
    get_engine()
    with SessionLocal() as db:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            if existing_user.user_role == UserRole.ADMIN.value:
                typer.echo(
                    f"Error: User with email '{email}' is already an admin.",
                    err=True,
                )
            else:
                typer.echo(
                    f"Error: User with email '{email}' "
                    "already exists but is not an admin. "
                    "Use the 'promote-admin' command to "
                    "promote them instead.",
                    err=True,
                )
            raise typer.Exit(code=1)

        # Create new admin user
        hashed_pw = security_service.hash_password(password)
        admin_user = User(
            email=email,
            full_name=full_name,
            hashed_password=hashed_pw,
            user_role=UserRole.ADMIN.value,
            is_active=True,
            is_verified=True,
        )
        db.add(admin_user)
        db.commit()
        typer.echo(f"Successfully created admin user: {email}")


@app_cli.command()
def promote_admin(
    email: str = typer.Option(
        None,
        "--email",
        "-e",
        help="Email address of the user to promote to admin.",
    ),
) -> None:
    """Promote an existing user to admin role."""
    if not email:
        email = typer.prompt("Email of user to promote")

    email = email.strip().lower()

    get_engine()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            typer.echo(f"Error: User with email '{email}' does not exist.", err=True)
            raise typer.Exit(code=1)

        if user.user_role == UserRole.ADMIN.value:
            typer.echo(f"User '{email}' is already an admin.")
            return

        user.user_role = UserRole.ADMIN.value
        db.commit()
        typer.echo(f"Successfully promoted user '{email}' to admin role.")


@app_cli.command()
def demote_admin(
    email: str = typer.Option(
        None,
        "--email",
        "-e",
        help="Email address of the admin user to demote.",
    ),
) -> None:
    """Demote an admin back to regular user role."""
    if not email:
        email = typer.prompt("Email of admin to demote")

    email = email.strip().lower()

    get_engine()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            typer.echo(f"Error: User with email '{email}' does not exist.", err=True)
            raise typer.Exit(code=1)

        if user.user_role != UserRole.ADMIN.value:
            typer.echo(f"Error: User with email '{email}' is not an admin.", err=True)
            raise typer.Exit(code=1)

        # Safety Check: Prevent demoting the last remaining admin user
        admin_count = (
            db.query(User).filter(User.user_role == UserRole.ADMIN.value).count()
        )
        if admin_count <= 1:
            typer.echo(
                "Error: Cannot demote the last remaining admin.",
                err=True,
            )
            raise typer.Exit(code=1)

        user.user_role = UserRole.USER.value
        db.commit()
        typer.echo(f"Successfully demoted admin '{email}' to regular user role.")


@app_cli.command()
def list_admins() -> None:
    """List all users with the admin role."""
    get_engine()
    with SessionLocal() as db:
        admins = db.query(User).filter(User.user_role == UserRole.ADMIN.value).all()
        if not admins:
            typer.echo("No admin users found.")
            return

        typer.echo(f"{'Email':<35} | {'Full Name':<25} | {'Created At':<25}")
        typer.echo("-" * 90)
        for admin in admins:
            created_str = (
                admin.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if admin.created_at
                else "N/A"
            )
            name_str = admin.full_name or "N/A"
            typer.echo(f"{admin.email:<35} | {name_str:<25} | {created_str:<25}")


if __name__ == "__main__":
    app_cli()
