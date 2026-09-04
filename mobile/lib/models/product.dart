class Product {
  final String id;
  final String nameZh;
  final String nameEn;
  final String sku;
  final String barcode;
  final int priceCents;
  final int costCents;
  final double stock;
  final String unit;
  final String category;
  final int isDeleted;

  const Product({
    required this.id,
    required this.nameZh,
    required this.nameEn,
    required this.sku,
    required this.barcode,
    required this.priceCents,
    this.costCents = 0,
    this.stock = 0,
    this.unit = 'pcs',
    this.category = '',
    this.isDeleted = 0,
  });

  String get label => '$nameZh / $nameEn';

  Product copyWith({
    String? nameZh,
    String? nameEn,
    String? sku,
    String? barcode,
    int? priceCents,
    int? costCents,
    double? stock,
    String? unit,
    String? category,
    int? isDeleted,
  }) =>
      Product(
        id: id,
        nameZh: nameZh ?? this.nameZh,
        nameEn: nameEn ?? this.nameEn,
        sku: sku ?? this.sku,
        barcode: barcode ?? this.barcode,
        priceCents: priceCents ?? this.priceCents,
        costCents: costCents ?? this.costCents,
        stock: stock ?? this.stock,
        unit: unit ?? this.unit,
        category: category ?? this.category,
        isDeleted: isDeleted ?? this.isDeleted,
      );

  Map<String, Object?> toMap() => {
        'id': id,
        'name_zh': nameZh,
        'name_en': nameEn,
        'sku': sku,
        'barcode': barcode,
        'price_cents': priceCents,
        'cost_cents': costCents,
        'stock': stock,
        'unit': unit,
        'category': category,
        'is_deleted': isDeleted,
      };

  factory Product.fromMap(Map<String, Object?> m) => Product(
        id: m['id']! as String,
        nameZh: m['name_zh']! as String,
        nameEn: m['name_en']! as String,
        sku: (m['sku'] as String?) ?? '',
        barcode: (m['barcode'] as String?) ?? '',
        priceCents: m['price_cents']! as int,
        costCents: (m['cost_cents'] as int?) ?? 0,
        stock: (m['stock'] as num?)?.toDouble() ?? 0,
        unit: (m['unit'] as String?) ?? 'pcs',
        category: (m['category'] as String?) ?? '',
        isDeleted: (m['is_deleted'] as int?) ?? 0,
      );

  factory Product.fromJson(Map<String, dynamic> j) => Product(
        id: j['id'] as String,
        nameZh: j['nameZh'] as String,
        nameEn: j['nameEn'] as String,
        sku: j['sku'] as String? ?? '',
        barcode: j['barcode'] as String? ?? '',
        priceCents: j['priceCents'] as int,
        costCents: j['costCents'] as int? ?? 0,
        stock: (j['stock'] as num?)?.toDouble() ?? 0,
        unit: j['unit'] as String? ?? 'pcs',
        category: j['category'] as String? ?? '',
      );
}
