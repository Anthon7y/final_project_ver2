from sqlalchemy import or_
from backend.models import db, Furniture, User, Favorite


def _split(val):
    return [v.strip() for v in str(val).split(',') if v.strip()]


class Database:

    def get_distinct_values(self, column):
        col = getattr(Furniture, column)
        rows = db.session.query(col).filter(col.isnot(None)).distinct().all()
        result = set()
        for (val,) in rows:
            for v in _split(val):
                if v.lower() != 'none':
                    result.add(v)
        return list(result)

    def search_furniture(self, furniture_type=None, min_price=None, max_price=None,
                         width=None, length=None, height=None,
                         materials=None, colors=None, brand=None, style=None, limit=20):
        q = db.session.query(Furniture)
        if furniture_type: q = q.filter(Furniture.type == furniture_type.strip())
        if min_price:
            try: q = q.filter(Furniture.price >= float(min_price))
            except (ValueError, TypeError): pass
        if max_price:
            try: q = q.filter(Furniture.price <= float(max_price))
            except (ValueError, TypeError): pass
        if width:
            try: q = q.filter(Furniture.width <= float(width))
            except (ValueError, TypeError): pass
        if length:
            try: q = q.filter(Furniture.length <= float(length))
            except (ValueError, TypeError): pass
        if height:
            try: q = q.filter(Furniture.height <= float(height))
            except (ValueError, TypeError): pass
        for val, col in [(materials, Furniture.materials), (colors, Furniture.colors)]:
            if val:
                parts = _split(val) if not isinstance(val, list) else [v for m in val for v in _split(m)]
                if parts:
                    q = q.filter(or_(*[col.ilike(f'%{v}%') for v in parts]))
        if brand: q = q.filter(Furniture.brand.ilike(f'%{brand.strip()}%'))
        if style:
            parts = _split(style)
            if parts: q = q.filter(or_(*[Furniture.style.ilike(f'%{s}%') for s in parts]))
        return [f.to_dict() for f in q.order_by(Furniture.price.asc()).limit(limit).all()]

    def add_furniture(self, data):
        item = Furniture(**{k: data.get(k) for k in
            ['name','type','price','width','length','height','materials',
             'colors','brand','style','image_url','product_url','is_new']})
        db.session.add(item); db.session.commit()
        return item.id

    def create_user(self, username, password_hash):
        try:
            u = User(username=username, password_hash=password_hash)
            db.session.add(u); db.session.commit()
            return u.id
        except Exception:
            db.session.rollback(); return None

    def get_user_by_username(self, username):
        u = User.query.filter_by(username=username).first()
        return {'id': u.id, 'username': u.username, 'password_hash': u.password_hash} if u else None

    def add_to_favorites(self, user_id, furniture_id):
        if not Furniture.query.get(furniture_id): return False
        try:
            db.session.add(Favorite(user_id=user_id, furniture_id=furniture_id))
            db.session.commit(); return True
        except Exception:
            db.session.rollback(); return False

    def remove_from_favorites(self, user_id, furniture_id):
        Favorite.query.filter_by(user_id=user_id, furniture_id=furniture_id).delete()
        db.session.commit()

    def get_favorites(self, user_id):
        return [f.to_dict() for f in
                db.session.query(Furniture)
                .join(Favorite, Favorite.furniture_id == Furniture.id)
                .filter(Favorite.user_id == user_id)
                .order_by(Favorite.created_at.desc()).all()]
